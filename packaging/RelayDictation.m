#import "RelayDictation.h"
#import <AVFoundation/AVFoundation.h>
#import <Speech/Speech.h>

static const NSTimeInterval MaxListenSeconds = 55; // Apple's recognizer stops after about a minute
static const NSTimeInterval FinishGraceSeconds = 1.5; // after the person lets go, how long the last words may take

@interface RelayDictation ()
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL finishing;                 // the person let go; waiting for the last words
@property(nonatomic) BOOL tapInstalled;
@property(nonatomic) NSUInteger session;             // each start has a number, so late answers from an older one are ignored
@property(nonatomic, strong) AVAudioEngine *engine;
@property(nonatomic, strong) SFSpeechRecognizer *recognizer;
@property(nonatomic, strong) SFSpeechAudioBufferRecognitionRequest *request;
@property(nonatomic, strong) SFSpeechRecognitionTask *task;
@property(nonatomic, copy) NSString *latest;
@property(nonatomic, strong) NSTimer *limitTimer;
@property(nonatomic, strong) NSTimer *graceTimer;
@end

@implementation RelayDictation

- (void)report:(NSString *)state text:(NSString *)text error:(NSString *)error {
    id<RelayDictationDelegate> delegate = self.delegate;
    if (delegate) [delegate dictation:self reports:state text:text ?: @"" error:error];
}

// Stops everything and forgets it. Answers that arrive afterwards belong to an older session and are ignored.
- (void)teardown {
    self.session += 1;
    [self.limitTimer invalidate];
    [self.graceTimer invalidate];
    self.limitTimer = nil;
    self.graceTimer = nil;
    if (self.engine) {
        if (self.engine.isRunning) [self.engine stop];
        if (self.tapInstalled) [self.engine.inputNode removeTapOnBus:0];
    }
    self.tapInstalled = NO;
    [self.task cancel];
    self.task = nil;
    self.request = nil;
    self.recognizer = nil;
    self.engine = nil;
    self.active = NO;
    self.finishing = NO;
}

- (void)failWith:(NSString *)code {
    [self teardown];
    [self report:@"error" text:@"" error:code];
}

- (void)startWithLocale:(NSString *)identifier {
    if (self.active) return;
    self.active = YES;
    self.finishing = NO;
    self.latest = @"";
    NSUInteger session = ++self.session;
    __weak RelayDictation *weakSelf = self;
    // The first time, macOS asks twice: for speech recognition, then for the microphone.
    [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus status) {
        dispatch_async(dispatch_get_main_queue(), ^{
            RelayDictation *strongSelf = weakSelf;
            if (!strongSelf || session != strongSelf.session || !strongSelf.active) return;
            if (status != SFSpeechRecognizerAuthorizationStatusAuthorized) {
                [strongSelf failWith:@"speech-denied"];
                return;
            }
            [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted) {
                dispatch_async(dispatch_get_main_queue(), ^{
                    RelayDictation *again = weakSelf;
                    if (!again || session != again.session || !again.active) return;
                    if (!granted) {
                        [again failWith:@"mic-denied"];
                        return;
                    }
                    [again beginListeningWithLocale:identifier session:session];
                });
            }];
        });
    }];
}

- (void)beginListeningWithLocale:(NSString *)identifier session:(NSUInteger)session {
    SFSpeechRecognizer *recognizer = [[SFSpeechRecognizer alloc] initWithLocale:[NSLocale localeWithLocaleIdentifier:identifier]];
    if (!recognizer || !recognizer.isAvailable) {
        [self failWith:@"unavailable"];
        return;
    }
    SFSpeechAudioBufferRecognitionRequest *request = [[SFSpeechAudioBufferRecognitionRequest alloc] init];
    request.shouldReportPartialResults = YES;
    if (recognizer.supportsOnDeviceRecognition) request.requiresOnDeviceRecognition = YES; // the audio stays on this Mac
    if (@available(macOS 13.0, *)) request.addsPunctuation = YES;

    AVAudioEngine *engine = [[AVAudioEngine alloc] init];
    AVAudioInputNode *input = engine.inputNode;
    AVAudioFormat *format = [input outputFormatForBus:0];
    if (format.sampleRate <= 0 || format.channelCount == 0) { // no microphone is connected
        [self failWith:@"unavailable"];
        return;
    }
    [input installTapOnBus:0 bufferSize:1024 format:format block:^(AVAudioPCMBuffer *buffer, AVAudioTime *when) {
        [request appendAudioPCMBuffer:buffer];
    }];
    self.engine = engine;
    self.tapInstalled = YES;
    [engine prepare];
    NSError *startError = nil;
    if (![engine startAndReturnError:&startError]) {
        [self failWith:@"failed"];
        return;
    }
    self.recognizer = recognizer;
    self.request = request;
    __weak RelayDictation *weakSelf = self;
    self.task = [recognizer recognitionTaskWithRequest:request resultHandler:^(SFSpeechRecognitionResult *result, NSError *error) {
        NSString *text = result.bestTranscription.formattedString;
        BOOL final = result.isFinal;
        dispatch_async(dispatch_get_main_queue(), ^{
            [weakSelf heard:text final:final failed:(error != nil) session:session];
        });
    }];
    self.limitTimer = [NSTimer scheduledTimerWithTimeInterval:MaxListenSeconds repeats:NO block:^(NSTimer *timer) {
        [weakSelf stop];
    }];
    [self report:@"listening" text:@"" error:nil];
}

- (void)heard:(NSString *)text final:(BOOL)final failed:(BOOL)failed session:(NSUInteger)session {
    if (session != self.session || !self.active) return;
    if (text.length) self.latest = text;
    // Done: the recognizer says so, or it gave up (nothing heard, or a time limit) and what there is will do.
    if (final || failed) {
        [self finishNow];
        return;
    }
    if (text.length) [self report:@"text" text:self.latest error:nil];
}

- (void)finishNow {
    NSString *text = self.latest ?: @"";
    [self teardown];
    [self report:@"done" text:text error:nil];
}

- (void)stop {
    if (!self.active || self.finishing) return;
    if (!self.engine) { // let go before the microphone was even open (for example while macOS was asking permission)
        [self teardown];
        [self report:@"done" text:@"" error:nil];
        return;
    }
    self.finishing = YES;
    [self.limitTimer invalidate];
    self.limitTimer = nil;
    if (self.engine.isRunning) [self.engine stop];
    if (self.tapInstalled) [self.engine.inputNode removeTapOnBus:0];
    self.tapInstalled = NO;
    [self.request endAudio];
    __weak RelayDictation *weakSelf = self;
    self.graceTimer = [NSTimer scheduledTimerWithTimeInterval:FinishGraceSeconds repeats:NO block:^(NSTimer *timer) {
        [weakSelf finishNow];
    }];
}

- (void)cancel {
    if (!self.active) return;
    [self teardown];
    [self report:@"cancelled" text:@"" error:nil];
}

@end
