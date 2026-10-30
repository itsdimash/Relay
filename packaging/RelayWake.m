#import "RelayWake.h"
#import "RelayNowPlaying.h"
#import <AVFoundation/AVFoundation.h>
#import <Speech/Speech.h>

static const NSTimeInterval TaskSeconds = 45;        // a recognition task is renewed before Apple's limit of about a minute
static const NSTimeInterval FirstWordsSeconds = 6;   // after "Hey Relay", how long to wait for the first words of the request
static const NSTimeInterval QuietSeconds = 1.4;      // no new words for this long: the request is over
static const NSTimeInterval RestartDelay = 0.6;      // a recognition task that ended starts again after this (never in a tight loop)
static const NSTimeInterval ResumeDelay = 0.5;       // after dictation or speech, the microphone is given a moment to settle
static const NSUInteger MaxRequestLength = 600;

// "Hey Relay" as the recognizer tends to write it, and the same in Russian. Either language is accepted whichever language
// is being listened for, because a person may say the English name in a Russian sentence and the other way round.
static NSRegularExpression *WakePattern(void) {
    static NSRegularExpression *pattern;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSString *english = @"(?:hey|hay|hi|okay|ok)[\\s,.!]+(?:relay|relai|re-lay|re lay|railay|rilay|rely)";
        NSString *russian = @"(?:эй|хей|хэй|привет|окей|ок)[\\s,.!]+(?:релей|релэй|рилей|рилэй|релай)";
        NSString *source = [NSString stringWithFormat:@"(?<![\\p{L}\\p{N}])(?:%@|%@)(?![\\p{L}\\p{N}])", english, russian];
        pattern = [NSRegularExpression regularExpressionWithPattern:source options:NSRegularExpressionCaseInsensitive error:nil];
    });
    return pattern;
}

// The words after the wake phrase (possibly none), or nil when the phrase has not been said in this text.
static NSString *WordsAfterWake(NSString *text) {
    NSTextCheckingResult *match = [WakePattern() firstMatchInString:text options:0 range:NSMakeRange(0, text.length)];
    if (!match) return nil;
    NSMutableCharacterSet *skip = [NSCharacterSet.whitespaceAndNewlineCharacterSet mutableCopy];
    [skip addCharactersInString:@",.!?;:-–—"];
    NSString *rest = [[text substringFromIndex:NSMaxRange(match.range)] stringByTrimmingCharactersInSet:skip];
    if (rest.length > MaxRequestLength) {
        NSRange range = [rest rangeOfComposedCharacterSequencesForRange:NSMakeRange(0, MaxRequestLength)];
        rest = [rest substringWithRange:range];
    }
    return rest;
}

@interface RelayWake ()
@property(nonatomic) BOOL enabled;
@property(nonatomic) BOOL paused;
@property(nonatomic) BOOL triggered;               // "Hey Relay" was heard: the request is being collected
@property(nonatomic) BOOL tapInstalled;
@property(nonatomic) BOOL starting;                // asking for permission, or setting the microphone up
@property(nonatomic) NSUInteger session;           // each start of the microphone has a number, so late answers from an older one are ignored
@property(nonatomic) NSUInteger taskID;            // and so does each recognition task
@property(nonatomic, copy) NSString *locale;
@property(nonatomic, copy) NSString *spoken;     // the words after "Hey Relay" so far
@property(nonatomic, strong) AVAudioEngine *engine;
@property(nonatomic, strong) SFSpeechRecognizer *recognizer;
@property(atomic, strong) SFSpeechAudioBufferRecognitionRequest *request; // read on the audio thread
@property(nonatomic, strong) SFSpeechRecognitionTask *task;
@property(nonatomic, strong) NSTimer *lifeTimer;
@property(nonatomic, strong) NSTimer *quietTimer;
@property(nonatomic, strong) NSTimer *firstTimer;
@property(nonatomic, strong) id configObserver;
@property(nonatomic) NSUInteger quickFailures;      // recognition tasks in a row that ended with an error almost at once
@property(nonatomic, strong) NSDate *taskStarted;
@end

@implementation RelayWake

- (instancetype)init {
    if ((self = [super init])) {
        __weak RelayWake *weakSelf = self;
        // The microphone changed (headphones connected, another input chosen): the engine stops by itself, so start it again.
        _configObserver = [NSNotificationCenter.defaultCenter addObserverForName:AVAudioEngineConfigurationChangeNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
            RelayWake *strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.engine || note.object != strongSelf.engine) return;
            [strongSelf teardownAudio];
            [strongSelf beginAfter:1.0];
        }];
    }
    return self;
}

- (void)dealloc {
    if (_configObserver) [NSNotificationCenter.defaultCenter removeObserver:_configObserver];
}

- (void)report:(NSString *)state text:(NSString *)text error:(NSString *)error {
    id<RelayWakeDelegate> delegate = self.delegate;
    if (delegate) [delegate wake:self reports:state text:text ?: @"" error:error];
}

#pragma mark - Turning it on and off

- (void)startWithLocale:(NSString *)identifier {
    if (self.enabled && [self.locale isEqualToString:identifier]) return;
    BOOL listening = self.enabled;
    self.enabled = YES;
    self.locale = identifier;
    if (listening) [self teardownAudio]; // another language: listen again for that one
    [self beginIfPossible];
}

- (void)stop {
    self.enabled = NO;
    [self teardownAudio];
}

- (void)pause {
    if (self.paused) return;
    self.paused = YES;
    [self teardownAudio];
}

- (void)resume {
    if (!self.paused) return;
    self.paused = NO;
    [self beginAfter:ResumeDelay];
}

- (void)beginAfter:(NSTimeInterval)seconds {
    __weak RelayWake *weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(seconds * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        [weakSelf beginIfPossible];
    });
}

// Stops everything and forgets it. Answers that arrive afterwards belong to an older session and are ignored.
- (void)teardownAudio {
    BOOL wasCollecting = self.triggered;
    self.session += 1;
    self.taskID += 1;
    self.starting = NO;
    self.triggered = NO;
    self.spoken = @"";
    [self.lifeTimer invalidate];
    [self.quietTimer invalidate];
    [self.firstTimer invalidate];
    self.lifeTimer = nil;
    self.quietTimer = nil;
    self.firstTimer = nil;
    if (self.engine) {
        if (self.engine.isRunning) [self.engine stop];
        if (self.tapInstalled) [self.engine.inputNode removeTapOnBus:0];
    }
    self.tapInstalled = NO;
    [self.request endAudio];
    self.request = nil;
    [self.task cancel];
    self.task = nil;
    self.recognizer = nil;
    self.engine = nil;
    if (wasCollecting) [self report:@"command" text:@"" error:nil]; // the page stops showing that it is listening
}

- (void)failWith:(NSString *)code {
    [RelayNowPlaying log:[NSString stringWithFormat:@"wake: stopped, %@", code]];
    self.enabled = NO;
    [self teardownAudio];
    [self report:@"error" text:@"" error:code];
}

#pragma mark - The microphone

- (void)beginIfPossible {
    if (!self.enabled || self.paused || self.engine || self.starting) return;
    self.starting = YES;
    NSUInteger session = ++self.session;
    __weak RelayWake *weakSelf = self;
    // The first time, macOS asks twice: for speech recognition, then for the microphone.
    [RelayNowPlaying log:[NSString stringWithFormat:@"wake: starting (%@)", self.locale]];
    [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus status) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [RelayNowPlaying log:[NSString stringWithFormat:@"wake: speech authorization %ld", (long)status]];
            RelayWake *strongSelf = weakSelf;
            if (!strongSelf || session != strongSelf.session) return;
            if (status != SFSpeechRecognizerAuthorizationStatusAuthorized) {
                [strongSelf failWith:@"speech-denied"];
                return;
            }
            [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) {
                dispatch_async(dispatch_get_main_queue(), ^{
                    [RelayNowPlaying log:[NSString stringWithFormat:@"wake: microphone access %@", granted ? @"granted" : @"refused"]];
                    RelayWake *again = weakSelf;
                    if (!again || session != again.session) return;
                    if (!granted) {
                        [again failWith:@"mic-denied"];
                        return;
                    }
                    [again listen];
                });
            }];
        });
    }];
}

- (void)listen {
    self.starting = NO;
    SFSpeechRecognizer *recognizer = [[SFSpeechRecognizer alloc] initWithLocale:[NSLocale localeWithLocaleIdentifier:self.locale]];
    if (!recognizer || !recognizer.isAvailable) {
        [self failWith:@"unavailable"];
        return;
    }
    // Listening all the time is only acceptable when what is heard never leaves the Mac.
    if (!recognizer.supportsOnDeviceRecognition) {
        [self failWith:@"ondevice"];
        return;
    }
    AVAudioEngine *engine = [[AVAudioEngine alloc] init];
    AVAudioInputNode *input = engine.inputNode;
    AVAudioFormat *format = [input outputFormatForBus:0];
    if (format.sampleRate <= 0 || format.channelCount == 0) { // no microphone is connected
        [self failWith:@"unavailable"];
        return;
    }
    __weak RelayWake *weakSelf = self;
    [input installTapOnBus:0 bufferSize:1024 format:format block:^(AVAudioPCMBuffer *buffer, AVAudioTime *when) {
        [weakSelf.request appendAudioPCMBuffer:buffer];
    }];
    self.engine = engine;
    self.tapInstalled = YES;
    self.recognizer = recognizer;
    [engine prepare];
    NSError *startError = nil;
    if (![engine startAndReturnError:&startError]) {
        [RelayNowPlaying log:[NSString stringWithFormat:@"wake: the audio engine did not start: %@", startError.localizedDescription]];
        [self failWith:@"failed"];
        return;
    }
    self.quickFailures = 0;
    [self startTask];
    [RelayNowPlaying log:@"wake: listening"];
    [self report:@"ready" text:@"" error:nil]; // the page can say that it is on
}

// A fresh recognition task with an empty transcript: after every request, and every so often because a task cannot run for long.
- (void)startTask {
    if (!self.recognizer || !self.engine) return;
    [self.lifeTimer invalidate];
    [self.task cancel];
    SFSpeechAudioBufferRecognitionRequest *request = [[SFSpeechAudioBufferRecognitionRequest alloc] init];
    request.shouldReportPartialResults = YES;
    request.requiresOnDeviceRecognition = YES;
    SFSpeechAudioBufferRecognitionRequest *old = self.request;
    self.request = request;
    [old endAudio];
    NSUInteger taskID = ++self.taskID;
    self.taskStarted = [NSDate date];
    __weak RelayWake *weakSelf = self;
    self.task = [self.recognizer recognitionTaskWithRequest:request resultHandler:^(SFSpeechRecognitionResult *result, NSError *error) {
        NSString *text = result.bestTranscription.formattedString ?: @"";
        BOOL ended = result.isFinal || error != nil;
        NSString *problem = error ? [NSString stringWithFormat:@"%@ %ld", error.domain, (long)error.code] : nil;
        dispatch_async(dispatch_get_main_queue(), ^{
            [weakSelf heard:text ended:ended task:taskID problem:problem];
        });
    }];
    self.lifeTimer = [NSTimer scheduledTimerWithTimeInterval:TaskSeconds repeats:NO block:^(NSTimer *timer) {
        RelayWake *strongSelf = weakSelf;
        if (!strongSelf) return;
        if (strongSelf.triggered) { // a request is being said: renew after it
            strongSelf.lifeTimer = [NSTimer scheduledTimerWithTimeInterval:3 repeats:NO block:^(NSTimer *again) { [weakSelf startTask]; }];
            return;
        }
        [strongSelf startTask];
    }];
}

- (void)restartTaskSoon {
    NSUInteger session = self.session;
    __weak RelayWake *weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(RestartDelay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        RelayWake *strongSelf = weakSelf;
        if (strongSelf && strongSelf.session == session && strongSelf.enabled && !strongSelf.paused && !strongSelf.triggered) [strongSelf startTask];
    });
}

#pragma mark - Hearing "Hey Relay"

- (void)heard:(NSString *)text ended:(BOOL)ended task:(NSUInteger)taskID problem:(NSString *)problem {
    if (taskID != self.taskID || !self.enabled) return; // an older task, or switched off meanwhile
    if (problem) {
        // Only the kind of error is written down, never what was said. Tasks that fail again and again at once mean the
        // recognizer cannot work here (usually the on-device language model is not installed): say so instead of looping.
        [RelayNowPlaying log:[NSString stringWithFormat:@"wake: recognition ended with %@", problem]];
        BOOL quick = self.taskStarted && -[self.taskStarted timeIntervalSinceNow] < 2.0 && !self.triggered && text.length == 0;
        self.quickFailures = quick ? self.quickFailures + 1 : 0;
        if (self.quickFailures >= 5) {
            [self failWith:@"ondevice"];
            return;
        }
    } else if (text.length) {
        self.quickFailures = 0;
    }
    NSString *after = WordsAfterWake(text);
    if (!self.triggered) {
        if (!after) {
            if (ended) [self restartTaskSoon]; // the task is over without the phrase: listen again
            return;
        }
        self.triggered = YES;
        self.spoken = @"";
        [RelayNowPlaying log:@"wake: heard the wake phrase"];
        [self report:@"heard" text:@"" error:nil];
        __weak RelayWake *weakSelf = self;
        self.firstTimer = [NSTimer scheduledTimerWithTimeInterval:FirstWordsSeconds repeats:NO block:^(NSTimer *timer) {
            [weakSelf finishRequest];
        }];
    }
    if (after.length) {
        self.spoken = after;
        [self.firstTimer invalidate];
        self.firstTimer = nil;
        [self.quietTimer invalidate];
        __weak RelayWake *weakSelf = self;
        self.quietTimer = [NSTimer scheduledTimerWithTimeInterval:QuietSeconds repeats:NO block:^(NSTimer *timer) {
            [weakSelf finishRequest];
        }];
    }
    if (ended) [self finishRequest];
}

// The person stopped talking (or never started): hand the request to the page and listen from scratch.
- (void)finishRequest {
    if (!self.triggered) return;
    NSString *request = self.spoken ?: @"";
    self.triggered = NO;
    self.spoken = @"";
    [self.quietTimer invalidate];
    [self.firstTimer invalidate];
    self.quietTimer = nil;
    self.firstTimer = nil;
    [self report:@"command" text:request error:nil];
    [self startTask]; // an empty transcript, so the same words are never heard twice
}

@end
