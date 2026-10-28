// Light and motion around the physical notch, drawn even while the notch panel is closed.
// A coloured halo breathes around the notch and sparks run around its edge: the cover's colour for music, the working
// agent's colour for agents (three sparks, one per agent, the one with the baton the longest).
// Only Macs with a notch get it; on other screens there is nothing to outline. It never takes mouse clicks.
#import <Cocoa/Cocoa.h>

@interface RelayNotchGlow : NSObject
// How the light looks, chosen by the person: "line" (a thin steady line on the notch edge, the quiet default),
// "halo" (the line with a soft breathing glow), "sparks" (the halo with bright sparks that circle the notch) or "off".
// Anything else counts as "line". Changing it restyles whatever is lit right now.
@property(nonatomic, copy) NSString *style;
// Music is playing. The colour is the cover's.
- (void)showMusicColor:(NSColor *)color;
// Agents are working: "observer", "builder", "reviewer", "you" (waiting for the person) or anything else.
- (void)showAgentActor:(NSString *)actor;
// A one-time ripple of light: a new track, or a new agent taking over.
- (void)burst;
// Relay has just started: a thin line draws itself along the notch from the middle outwards, a bloom of light follows,
// and three rings (one per agent) spread out and fade. About two seconds, once, whatever the glow style is.
// With reduced motion it is a plain fade of the line. Does nothing on a Mac without a notch.
- (void)playWelcome;
// Fades everything out.
- (void)hide;
// The notch screen was plugged in, unplugged or changed resolution.
- (void)screensChanged;
@end
