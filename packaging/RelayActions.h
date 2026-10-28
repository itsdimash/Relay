#import <Cocoa/Cocoa.h>

NS_ASSUME_NONNULL_BEGIN

// Done: a short state ("opened", "missing", "failed", "typed", "access", "gone", "changed") and a detail, usually the app's name.
typedef void (^RelayActionDone)(NSString *state, NSString *detail);

// Small things the voice can do on the Mac besides writing notes: open an app, put a draft into Telegram, type into the app
// the person was using. Every one of them is started by a person's words and a press (typing asks first); none of them sends,
// submits or presses Return.
@interface RelayActions : NSObject

// The app the person was working in. Relay's own panel never takes the front place, but if Relay itself is in front, this is
// the last other app that was. nil when there is none.
+ (nullable NSRunningApplication *)workingApplication;

// Opens the first of these names that is an installed app ("System Settings", then "System Preferences").
// Done: "opened" (detail: the app's name), "missing" or "failed".
+ (void)openApplicationNames:(NSArray<NSString *> *)names done:(RelayActionDone)done;

// Opens Telegram with these words ready to send. The person picks the chat and presses send; nothing is sent from here.
// Done: "opened", "missing" (Telegram is not installed) or "failed".
+ (void)draftTelegram:(NSString *)text done:(RelayActionDone)done;

// Types the words into the app, as if on the keyboard, on one line and without Return. macOS lets an app do this only after the
// person allows it under Privacy & Security, Accessibility; the first try asks. `prepare` runs once everything is ready, just
// before the first key (the panel steps out of the way there). Done: "typed" (detail: the app's name), "access" (not allowed
// yet), "gone" (the app quit) or "changed" (another app came to the front meanwhile; detail: its name).
+ (void)typeText:(NSString *)text
            into:(nullable NSRunningApplication *)target
         prepare:(dispatch_block_t)prepare
            done:(RelayActionDone)done;

@end

NS_ASSUME_NONNULL_END
