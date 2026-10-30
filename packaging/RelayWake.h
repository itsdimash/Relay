#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@class RelayWake;

@protocol RelayWakeDelegate <NSObject>
// What the wake word listener is doing, for the page:
//   "heard"    the person said "Hey Relay" and is now saying a request
//   "command"  the request, as the words after "Hey Relay" (empty when nothing was said)
//   "error"    error is one of: speech-denied, mic-denied, unavailable, ondevice, failed; listening has stopped
- (void)wake:(RelayWake *)wake reports:(NSString *)state text:(NSString *)text error:(nullable NSString *)error;
@end

// Listens all the time for "Hey Relay" (and "Эй, Релей"), then collects what is said after it until the person goes quiet.
// It runs only when the person turned it on, and only with speech recognition that runs on the Mac itself: when that is not
// available for the language it does not listen at all, so what is said is never sent anywhere. Nothing is recorded or kept.
@interface RelayWake : NSObject
@property(nonatomic, weak, nullable) id<RelayWakeDelegate> delegate;
@property(nonatomic, readonly) BOOL enabled;
- (void)startWithLocale:(NSString *)localeIdentifier; // for example "en-US" or "ru-RU"; the same language again changes nothing
- (void)stop;   // off
- (void)pause;  // the microphone or the speakers are needed for something else (dictation, an answer said out loud)
- (void)resume;
@end

NS_ASSUME_NONNULL_END
