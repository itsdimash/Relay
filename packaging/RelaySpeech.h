#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@class RelaySpeech;

@protocol RelaySpeechDelegate <NSObject>
// What the voice is doing, for the page:
//   "start"        the words are being spoken
//   "end"          finished, or stopped
//   "unavailable"  this Mac has no voice for the language
- (void)speech:(RelaySpeech *)speech reports:(NSString *)state;
@end

// Says an answer out loud with the Mac's own voices. Nothing is sent anywhere: the voice runs on the Mac.
@interface RelaySpeech : NSObject
@property(nonatomic, weak, nullable) id<RelaySpeechDelegate> delegate;
- (void)speak:(NSString *)text locale:(NSString *)localeIdentifier; // for example "en-US" or "ru-RU"; replaces what is being said
- (void)stop;
@end

NS_ASSUME_NONNULL_END
