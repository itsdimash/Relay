// Reads what is playing on the Mac (Apple Music, Spotify, YouTube in Chrome, Yandex Music, anything that shows
// in Control Center) and sends play, pause, next and previous. It runs the bundled MediaRemote adapter,
// which Apple's own /usr/bin/perl loads, so no Automation permission is needed.
#import <Cocoa/Cocoa.h>

@interface RelayNowPlaying : NSObject
// Called on the main thread when the track or play state changes. nil means nothing is playing.
// Keys: title, artist, album, app (bundle id), playing (BOOL), artwork (data: URL or NSNull),
// elapsed and duration (seconds, or NSNull), rate (playback speed), updatedAt (when elapsed was true, ms since 1970).
@property(nonatomic, copy) void (^handler)(NSDictionary *state);
// Called on the main thread, after handler, when a different track starts playing. The very first snapshot
// after start does not count, so opening Relay while music plays is not a "change".
@property(nonatomic, copy) void (^trackChangeHandler)(NSDictionary *state);
// The latest state, or nil.
@property(nonatomic, readonly) NSDictionary *state;
// YES when the adapter is part of this app. A source build without it simply has no music strip.
@property(nonatomic, readonly) BOOL available;
// Appends a line to ~/Library/Logs/Relay/now-playing.log (titles are never written, only sizes and errors).
+ (void)log:(NSString *)message;
- (void)start;
- (void)stop;
// "toggle", "next" or "previous". Anything else is ignored.
- (void)sendCommand:(NSString *)command;
@end
