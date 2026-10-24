// Light and motion around the physical notch, drawn even while the notch panel is closed.
// A coloured halo breathes around the notch and sparks run around its edge: the cover's colour for music, the working
// agent's colour for agents (three sparks, one per agent, the one with the baton the longest).
// Only Macs with a notch get it; on other screens there is nothing to outline. It never takes mouse clicks.
#import <Cocoa/Cocoa.h>

@interface RelayNotchGlow : NSObject
// Music is playing. The colour is the cover's.
- (void)showMusicColor:(NSColor *)color;
// Agents are working: "observer", "builder", "reviewer", "you" (waiting for the person) or anything else.
- (void)showAgentActor:(NSString *)actor;
// A one-time ripple of light: a new track, or a new agent taking over.
- (void)burst;
// Fades everything out.
- (void)hide;
// The notch screen was plugged in, unplugged or changed resolution.
- (void)screensChanged;
@end
