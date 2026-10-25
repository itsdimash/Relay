// A dark panel that slides down from the top edge of the screen, where the notch is.
// It shows the live Relay task (steps, the agent room, Approve and Reject) from the local engine.
#import <Cocoa/Cocoa.h>

extern NSString *const RelayNotchEnabledKey;

@protocol RelayNotchPanelDelegate <NSObject>
// The person pressed "Open Relay" in the panel.
- (void)notchPanelRequestsOpenRelay;
- (void)notchPanelRequestsOpenRelayAt:(NSDictionary *)destination;
@end

@interface RelayNotchPanel : NSObject
@property(nonatomic, weak) id<RelayNotchPanelDelegate> delegate;
// Turned on by default. Saved in the app's preferences.
@property(nonatomic) BOOL enabled;
// pageURL is the engine's /notch page, for example http://127.0.0.1:48765/notch.
- (instancetype)initWithPageURL:(NSURL *)pageURL;
// Slides the panel down now and keeps it until the pointer has been over it and left.
- (void)showPinned;
// Opens the panel and keeps it until toggled again, or closes it. Double-tapping the right Command key does this.
- (void)toggle;
@end
