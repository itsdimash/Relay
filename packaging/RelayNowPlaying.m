#import "RelayNowPlaying.h"

static NSString *const PerlPath = @"/usr/bin/perl";
static const NSUInteger MaxBufferBytes = 8 * 1024 * 1024;     // a line longer than this is not real data
static const NSUInteger MaxArtworkCharacters = 3 * 1024 * 1024; // base64 text, about 2 MB of image
static const NSInteger MaxFailures = 6;                        // consecutive failed starts before giving up

@interface RelayNowPlaying ()
@property(nonatomic, strong) NSTask *task;
@property(nonatomic, strong) NSMutableData *buffer; // only used by the reader callback
@property(nonatomic, strong) NSDictionary *state;
@property(nonatomic) BOOL wanted;
@property(nonatomic) NSInteger failures;
@property(nonatomic) NSInteger generation; // ignores callbacks from a stream that was already stopped
@property(nonatomic) BOOL primed;            // the first snapshot of this stream has been seen
@property(nonatomic, copy) NSString *lastTrackKey;
@end

// A number from the adapter that is usable as a time in seconds, or nil.
static NSNumber *FiniteNumberOrNull(id value) {
    if (![value isKindOfClass:NSNumber.class]) return nil;
    double number = [value doubleValue];
    return (isfinite(number) && number >= 0) ? value : nil;
}

// The adapter stamps the moment the elapsed time was true as an ISO 8601 string. Falls back to now.
static double TimestampMilliseconds(id value) {
    if ([value isKindOfClass:NSString.class]) {
        NSISO8601DateFormatter *formatter = [[NSISO8601DateFormatter alloc] init];
        NSDate *date = [formatter dateFromString:value];
        if (!date) {
            formatter.formatOptions = NSISO8601DateFormatWithInternetDateTime | NSISO8601DateFormatWithFractionalSeconds;
            date = [formatter dateFromString:value];
        }
        if (date) return round(date.timeIntervalSince1970 * 1000);
    }
    return round([NSDate date].timeIntervalSince1970 * 1000);
}

@implementation RelayNowPlaying

+ (void)log:(NSString *)message {
    static dispatch_queue_t queue;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ queue = dispatch_queue_create("com.itsdimash.relay.nowplaying-log", DISPATCH_QUEUE_SERIAL); });
    NSString *line = [NSString stringWithFormat:@"%@ %@\n", [NSDate date], message];
    dispatch_async(queue, ^{
        NSFileManager *files = NSFileManager.defaultManager;
        NSString *folder = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Relay"];
        [files createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *path = [folder stringByAppendingPathComponent:@"now-playing.log"];
        NSDictionary *attributes = [files attributesOfItemAtPath:path error:nil];
        if (attributes.fileSize > 256 * 1024) [files removeItemAtPath:path error:nil]; // keep it small
        NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:path];
        if (!handle) {
            [line writeToFile:path atomically:NO encoding:NSUTF8StringEncoding error:nil];
            return;
        }
        [handle seekToEndOfFile];
        [handle writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
        [handle closeFile];
    });
}

- (instancetype)init {
    self = [super init];
    if (self) {
        // The adapter is a child process: make sure it does not outlive the app.
        [NSNotificationCenter.defaultCenter addObserver:self
                                               selector:@selector(applicationWillTerminate:)
                                                   name:NSApplicationWillTerminateNotification
                                                 object:nil];
    }
    return self;
}

- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
    self.handler = nil;
    [self stop];
}

- (void)applicationWillTerminate:(NSNotification *)note {
    [self stop];
}

#pragma mark - Paths

- (NSString *)scriptPath {
    return [NSBundle.mainBundle pathForResource:@"mediaremote-adapter" ofType:@"pl"];
}

- (NSString *)frameworkPath {
    NSString *folder = NSBundle.mainBundle.privateFrameworksPath;
    return folder ? [folder stringByAppendingPathComponent:@"MediaRemoteAdapter.framework"] : nil;
}

- (BOOL)available {
    NSFileManager *files = NSFileManager.defaultManager;
    NSString *script = [self scriptPath], *framework = [self frameworkPath];
    return script && framework && [files fileExistsAtPath:script] && [files fileExistsAtPath:framework] &&
           [files isExecutableFileAtPath:PerlPath];
}

#pragma mark - Streaming

- (void)start {
    self.wanted = YES;
    self.failures = 0;
    [RelayNowPlaying log:[NSString stringWithFormat:@"start: available=%d script=%@ framework=%@", self.available, [self scriptPath], [self frameworkPath]]];
    [self launchStream];
}

- (void)stop {
    self.wanted = NO;
    self.generation += 1;
    [self terminateTask];
    [self publish:nil];
}

- (void)terminateTask {
    NSTask *task = self.task;
    self.task = nil;
    if (!task) return;
    task.terminationHandler = nil;
    [(NSPipe *)task.standardOutput fileHandleForReading].readabilityHandler = nil;
    if (task.isRunning) [task terminate]; // the adapter exits on SIGTERM
}

- (void)launchStream {
    if (!self.wanted || self.task || ![self available]) return;
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:PerlPath];
    // --no-diff: every line is a complete snapshot, so there is nothing to merge.
    task.arguments = @[ [self scriptPath], [self frameworkPath], @"stream", @"--no-diff", @"--debounce=150" ];
    NSPipe *output = [NSPipe pipe];
    task.standardOutput = output;
    NSPipe *errors = [NSPipe pipe];
    task.standardError = errors;
    task.standardInput = NSFileHandle.fileHandleWithNullDevice;
    errors.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (data.length == 0) {
            handle.readabilityHandler = nil;
            return;
        }
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"(not text)";
        [RelayNowPlaying log:[NSString stringWithFormat:@"adapter said: %@", text.length > 600 ? [text substringToIndex:600] : text]];
    };

    NSInteger generation = self.generation;
    self.primed = NO;
    self.buffer = [NSMutableData data];
    __weak RelayNowPlaying *weakSelf = self;
    output.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (data.length == 0) {
            handle.readabilityHandler = nil; // end of output; the termination handler does the rest
            return;
        }
        [weakSelf consume:data generation:generation];
    };
    task.terminationHandler = ^(NSTask *finished) {
        [RelayNowPlaying log:[NSString stringWithFormat:@"adapter exited: status=%d reason=%ld", finished.terminationStatus, (long)finished.terminationReason]];
        dispatch_async(dispatch_get_main_queue(), ^{
            RelayNowPlaying *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.generation != generation) return;
            strongSelf.task = nil;
            [strongSelf publish:nil];
            [strongSelf scheduleRestart];
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        [RelayNowPlaying log:[NSString stringWithFormat:@"could not start the adapter: %@", error]];
        [self scheduleRestart];
        return;
    }
    [RelayNowPlaying log:[NSString stringWithFormat:@"adapter started, pid %d", task.processIdentifier]];
    self.task = task;
}

// A stream that keeps dying is not worth retrying forever: back off, then give up quietly.
- (void)scheduleRestart {
    if (!self.wanted) return;
    self.failures += 1;
    if (self.failures > MaxFailures) return;
    NSTimeInterval delay = MIN(60.0, pow(2.0, (double)self.failures));
    NSInteger generation = self.generation;
    __weak RelayNowPlaying *weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        RelayNowPlaying *strongSelf = weakSelf;
        if (strongSelf && strongSelf.generation == generation) [strongSelf launchStream];
    });
}

// Runs on the reader's queue. Splits the bytes into lines and publishes the newest complete snapshot.
- (void)consume:(NSData *)data generation:(NSInteger)generation {
    [self.buffer appendData:data];
    if (self.buffer.length > MaxBufferBytes) {
        self.buffer.length = 0;
        return;
    }
    NSData *newline = [NSData dataWithBytes:"\n" length:1];
    id latest = nil;
    BOOL sawLine = NO;
    while (YES) {
        NSRange found = [self.buffer rangeOfData:newline options:0 range:NSMakeRange(0, self.buffer.length)];
        if (found.location == NSNotFound) break;
        NSData *line = [self.buffer subdataWithRange:NSMakeRange(0, found.location)];
        [self.buffer replaceBytesInRange:NSMakeRange(0, found.location + 1) withBytes:NULL length:0];
        if (line.length == 0) continue;
        id parsed = [self stateFromLine:line];
        [RelayNowPlaying log:[NSString stringWithFormat:@"line of %lu bytes -> %@", (unsigned long)line.length,
                              [parsed isKindOfClass:NSDictionary.class] ? [NSString stringWithFormat:@"playing=%@ titleLength=%lu hasArtwork=%d", parsed[@"playing"], (unsigned long)[parsed[@"title"] length], [parsed[@"artwork"] isKindOfClass:NSString.class]]
                                                                         : (parsed ? @"nothing playing" : @"ignored")]];
        if (parsed) {
            sawLine = YES;
            latest = parsed;
        }
    }
    if (!sawLine) return;
    NSDictionary *state = [latest isKindOfClass:NSDictionary.class] ? latest : nil;
    __weak RelayNowPlaying *weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        RelayNowPlaying *strongSelf = weakSelf;
        if (!strongSelf || strongSelf.generation != generation) return;
        strongSelf.failures = 0; // it is working
        [strongSelf publish:state];
        strongSelf.primed = YES;
    });
}

// Returns an NSDictionary for something playing, NSNull for nothing playing, or nil for a line to ignore.
- (id)stateFromLine:(NSData *)line {
    id object = [NSJSONSerialization JSONObjectWithData:line options:0 error:nil];
    if (![object isKindOfClass:NSDictionary.class]) return nil;
    NSDictionary *message = object;
    if (![message[@"type"] isEqual:@"data"]) return nil;
    NSDictionary *payload = [message[@"payload"] isKindOfClass:NSDictionary.class] ? message[@"payload"] : @{};
    NSString *title = [payload[@"title"] isKindOfClass:NSString.class] ? payload[@"title"] : @"";
    if (title.length == 0) return NSNull.null;

    NSString *artist = [payload[@"artist"] isKindOfClass:NSString.class] ? payload[@"artist"] : @"";
    NSString *album = [payload[@"album"] isKindOfClass:NSString.class] ? payload[@"album"] : @"";
    NSString *app = [payload[@"bundleIdentifier"] isKindOfClass:NSString.class] ? payload[@"bundleIdentifier"] : @"";
    BOOL playing = [payload[@"playing"] respondsToSelector:@selector(boolValue)] && [payload[@"playing"] boolValue];

    // Artwork becomes a data: URL, but only for plain image types and a sensible size.
    id artwork = NSNull.null;
    NSString *mime = [payload[@"artworkMimeType"] isKindOfClass:NSString.class] ? payload[@"artworkMimeType"] : @"";
    NSString *base64 = [payload[@"artworkData"] isKindOfClass:NSString.class] ? payload[@"artworkData"] : @"";
    NSSet *imageTypes = [NSSet setWithObjects:@"image/png", @"image/jpeg", @"image/gif", @"image/webp", nil];
    if (base64.length > 0 && base64.length <= MaxArtworkCharacters && [imageTypes containsObject:mime]) {
        artwork = [NSString stringWithFormat:@"data:%@;base64,%@", mime, base64];
    }
    // Where the track is, so the panel can draw a progress bar without asking again every second.
    NSNumber *elapsed = FiniteNumberOrNull(payload[@"elapsedTime"]);
    NSNumber *duration = FiniteNumberOrNull(payload[@"duration"]);
    double speed = [FiniteNumberOrNull(payload[@"playbackRate"]) doubleValue];
    if (speed <= 0) speed = playing ? 1 : 0;
    return @{ @"title": title, @"artist": artist, @"album": album, @"app": app, @"playing": @(playing), @"artwork": artwork,
              @"elapsed": elapsed ?: NSNull.null, @"duration": duration ?: NSNull.null, @"rate": @(speed),
              @"updatedAt": @(TimestampMilliseconds(payload[@"timestamp"])) };
}

- (void)publish:(id)state {
    NSDictionary *next = [state isKindOfClass:NSDictionary.class] ? state : nil;
    if ((self.state == nil && next == nil) || [self.state isEqualToDictionary:next]) return;
    self.state = next;
    if (self.handler) self.handler(next);
    if (!next) return;
    // A different song, playing now, after the first snapshot. Pausing, seeking and late artwork are not changes.
    NSString *key = [NSString stringWithFormat:@"%@\n%@\n%@\n%@", next[@"app"], next[@"title"], next[@"artist"], next[@"album"]];
    BOOL changed = ![key isEqualToString:self.lastTrackKey ?: @""];
    self.lastTrackKey = key;
    if (changed && self.primed && [next[@"playing"] boolValue] && self.trackChangeHandler) self.trackChangeHandler(next);
}

#pragma mark - Commands

- (void)sendCommand:(NSString *)command {
    if (![command isKindOfClass:NSString.class] || ![self available]) return;
    // MediaRemoteAdapter.h: kMRATogglePlayPause = 2, kMRANextTrack = 4, kMRAPreviousTrack = 5.
    NSDictionary *codes = @{ @"toggle": @"2", @"next": @"4", @"previous": @"5" };
    NSString *code = codes[command];
    if (!code) return;
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:PerlPath];
    task.arguments = @[ [self scriptPath], [self frameworkPath], @"send", code ];
    task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
    task.standardError = NSFileHandle.fileHandleWithNullDevice;
    task.standardInput = NSFileHandle.fileHandleWithNullDevice;
    [task launchAndReturnError:nil];
}

@end
