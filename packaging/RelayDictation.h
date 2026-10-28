#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@class RelayDictation;

@protocol RelayDictationDelegate <NSObject>
// What the microphone is doing, for the page:
//   "listening"  the microphone is open
//   "text"       the words heard so far (they may still change)
//   "done"       the final words (empty when nothing was said)
//   "cancelled"  thrown away on purpose
//   "error"      error is one of: speech-denied, mic-denied, unavailable, failed
- (void)dictation:(RelayDictation *)dictation reports:(NSString *)state text:(NSString *)text error:(nullable NSString *)error;
@end

// Turns what the person says into text, using Apple's speech recognition. Where the Mac supports it for the
// language, the audio is recognized on the Mac itself and never leaves it.
@interface RelayDictation : NSObject
@property(nonatomic, weak, nullable) id<RelayDictationDelegate> delegate;
@property(nonatomic, readonly) BOOL active;
- (void)startWithLocale:(NSString *)localeIdentifier; // for example "en-US" or "ru-RU"
- (void)stop;   // the person let go: report the final words
- (void)cancel; // throw it away
@end

NS_ASSUME_NONNULL_END
