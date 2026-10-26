#import "RelayNotchGlow.h"
#import <QuartzCore/QuartzCore.h>

static const CGFloat GlowSide = 56;     // room beside the notch for the halo to spread
static const CGFloat GlowBottom = 52;   // room below it for the halo
static const CGFloat NotchCornerRadius = 9;
static const NSInteger SparkCount = 3;

typedef NS_ENUM(NSInteger, RelayGlowKind) { RelayGlowKindNone, RelayGlowKindMusic, RelayGlowKindAgents };

static BOOL IsGlowStyle(NSString *style) { return style && [@[ @"off", @"line", @"halo", @"sparks" ] containsObject:style]; }

static NSColor *RGB(CGFloat r, CGFloat g, CGFloat b) { return [NSColor colorWithSRGBRed:r / 255 green:g / 255 blue:b / 255 alpha:1]; }
static NSColor *Brighter(NSColor *color, CGFloat amount) { return [color blendedColorWithFraction:amount ofColor:NSColor.whiteColor] ?: color; }

static NSColor *AgentColor(NSString *role) {
    if ([role isEqualToString:@"observer"]) return RGB(77, 182, 201);
    if ([role isEqualToString:@"builder"]) return RGB(240, 166, 63);
    if ([role isEqualToString:@"reviewer"]) return RGB(161, 139, 240);
    if ([role isEqualToString:@"you"]) return RGB(242, 178, 76);
    return RGB(79, 181, 148);
}

// A non-activating panel, not a plain window: only panels of this kind stay visible over other apps,
// over full-screen apps and on every Space, whichever app is in front.
@interface RelayGlowWindow : NSPanel
@end

@implementation RelayGlowWindow
- (BOOL)canBecomeKeyWindow { return NO; }
- (BOOL)canBecomeMainWindow { return NO; }
// The glow sits in the menu-bar band; the system must not push it down below the menu bar.
- (NSRect)constrainFrameRect:(NSRect)frameRect toScreen:(NSScreen *)screen { return frameRect; }
@end

@interface RelayNotchGlow ()
@property(nonatomic, strong) RelayGlowWindow *window;
@property(nonatomic, strong) CALayer *root;
@property(nonatomic, strong) CAShapeLayer *halo;     // wide, soft light
@property(nonatomic, strong) CAShapeLayer *outline;  // bright thin line on the notch edge
@property(nonatomic, strong) NSArray<CAShapeLayer *> *sparks;
@property(nonatomic) RelayGlowKind kind;
@property(nonatomic, copy) NSString *actor;
@property(nonatomic, strong) NSColor *color;
@property(nonatomic) BOOL visible;
@property(nonatomic) NSRect builtFrame;
@property(nonatomic) CGFloat notchWidth;
// What the app last asked to show, kept even while the style is "off", so changing the style can show it again.
@property(nonatomic) RelayGlowKind wantKind;
@property(nonatomic, copy) NSString *wantActor;
@property(nonatomic, strong) NSColor *wantColor;
@end

@implementation RelayNotchGlow

- (instancetype)init {
    self = [super init];
    if (self) {
        _style = @"line";
        [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(screensChanged)
                                                   name:NSApplicationDidChangeScreenParametersNotification object:nil];
    }
    return self;
}

- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
}

- (void)setStyle:(NSString *)style {
    NSString *clean = IsGlowStyle(style) ? style : @"line";
    if ([clean isEqualToString:_style]) return;
    _style = [clean copy];
    RelayGlowKind kind = self.wantKind;
    if (kind == RelayGlowKindNone) return; // nothing is lit right now: the new look shows the next time
    self.kind = RelayGlowKindNone;         // so that present: restyles instead of keeping what it has
    [self present:kind actor:self.wantActor color:self.wantColor];
}

#pragma mark - Window and layers

// The screen with a notch, and the notch's size.
- (NSScreen *)notchScreenSize:(NSSize *)size {
    if (@available(macOS 12.0, *)) {
        for (NSScreen *screen in NSScreen.screens) {
            if (screen.safeAreaInsets.top <= 0) continue;
            NSRect left = screen.auxiliaryTopLeftArea, right = screen.auxiliaryTopRightArea;
            if (NSIsEmptyRect(left) || NSIsEmptyRect(right) || NSMinX(right) <= NSMaxX(left)) continue;
            if (size) *size = NSMakeSize(NSMinX(right) - NSMaxX(left), screen.safeAreaInsets.top);
            return screen;
        }
    }
    return nil;
}

- (CAShapeLayer *)shapeLayerWithWidth:(CGFloat)width {
    CAShapeLayer *layer = [CAShapeLayer layer];
    layer.fillColor = nil;
    layer.lineWidth = width;
    layer.lineCap = kCALineCapRound;
    layer.shadowOffset = CGSizeZero;
    layer.shadowOpacity = 1;
    return layer;
}

- (void)buildLayersInView:(NSView *)view {
    self.root = view.layer;
    self.halo = [self shapeLayerWithWidth:9];
    self.halo.shadowRadius = 24;
    self.outline = [self shapeLayerWithWidth:3];
    self.outline.shadowRadius = 12;
    [self.root addSublayer:self.halo];
    [self.root addSublayer:self.outline];

    NSMutableArray *sparks = [NSMutableArray array];
    for (NSInteger i = 0; i < SparkCount; i++) {
        CAShapeLayer *spark = [self shapeLayerWithWidth:3.5];
        spark.strokeStart = 0;
        spark.strokeEnd = 0.2;
        spark.shadowRadius = 6;
        [self.root addSublayer:spark];
        [sparks addObject:spark];
    }
    self.sparks = sparks;
}

// Creates the window on first use and rebuilds the geometry when the notch moved or changed size.
- (BOOL)prepare {
    NSSize notch = NSZeroSize;
    NSScreen *screen = [self notchScreenSize:&notch];
    if (!screen) return NO;
    CGFloat width = notch.width + 2 * GlowSide, height = notch.height + GlowBottom;
    NSRect frame = NSMakeRect(NSMidX(screen.frame) - width / 2, NSMaxY(screen.frame) - height, width, height);
    if (self.window && NSEqualRects(frame, self.builtFrame)) return YES;

    if (!self.window) {
        RelayGlowWindow *window = [[RelayGlowWindow alloc] initWithContentRect:frame
                                                                     styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                                       backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO;
        window.hidesOnDeactivate = NO; // stays when another app takes over
        window.canHide = NO;           // stays when Relay itself is hidden with Command-H
        window.opaque = NO;
        window.backgroundColor = NSColor.clearColor;
        window.hasShadow = NO;
        window.ignoresMouseEvents = YES; // the pointer passes straight through to the notch hot zone
        window.level = NSMainMenuWindowLevel + 1; // under the panel, which is +2
        window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary |
                                    NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorIgnoresCycle;
        NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, width, height)];
        view.wantsLayer = YES;
        window.contentView = view;
        window.alphaValue = 0;
        self.window = window;
        [self buildLayersInView:view];
    }
    [self.window setFrame:frame display:NO];
    ((NSView *)self.window.contentView).frame = NSMakeRect(0, 0, width, height);

    // One U-shaped path along the bottom of the notch; everything that outlines it shares it.
    CGFloat x0 = GlowSide, x1 = GlowSide + notch.width, y0 = GlowBottom, r = NotchCornerRadius;
    CGMutablePathRef path = CGPathCreateMutable();
    CGPathMoveToPoint(path, NULL, x0, height);
    CGPathAddLineToPoint(path, NULL, x0, y0 + r);
    CGPathAddArcToPoint(path, NULL, x0, y0, x0 + r, y0, r);
    CGPathAddLineToPoint(path, NULL, x1 - r, y0);
    CGPathAddArcToPoint(path, NULL, x1, y0, x1, y0 + r, r);
    CGPathAddLineToPoint(path, NULL, x1, height);
    CGRect bounds = CGRectMake(0, 0, width, height);
    for (CAShapeLayer *layer in [@[ self.halo, self.outline ] arrayByAddingObjectsFromArray:self.sparks]) {
        layer.frame = bounds;
        layer.path = path;
    }
    CGPathRelease(path);

    self.notchWidth = notch.width;
    self.builtFrame = frame;
    return YES;
}

#pragma mark - Colours and motion

- (void)applyColors {
    BOOL music = self.kind == RelayGlowKindMusic;
    NSColor *main = music ? (self.color ?: AgentColor(nil)) : AgentColor(self.actor);
    NSColor *bright = Brighter(main, 0.55);
    self.halo.strokeColor = main.CGColor;
    self.halo.shadowColor = main.CGColor;
    self.outline.strokeColor = Brighter(main, 0.2).CGColor;
    self.outline.shadowColor = main.CGColor;

    BOOL softGlow = [self.style isEqualToString:@"halo"] || [self.style isEqualToString:@"sparks"];
    BOOL showSparks = [self.style isEqualToString:@"sparks"];
    self.halo.hidden = !softGlow;
    NSArray *roles = @[ @"observer", @"builder", @"reviewer" ];
    for (NSInteger i = 0; i < SparkCount; i++) {
        CAShapeLayer *spark = self.sparks[i];
        NSColor *colour = music ? bright : Brighter(AgentColor(roles[i]), 0.35);
        if (!music && [self.actor isEqualToString:@"you"]) colour = Brighter(AgentColor(@"you"), 0.35);
        spark.strokeColor = colour.CGColor;
        spark.shadowColor = colour.CGColor;
        spark.hidden = !showSparks || (music && i >= 2);
    }
}

// Every layer that has animations on it.
- (NSArray<CALayer *> *)animatedLayers {
    NSMutableArray<CALayer *> *layers = [NSMutableArray arrayWithObjects:self.halo, self.outline, nil];
    [layers addObjectsFromArray:self.sparks];
    return layers;
}

- (CABasicAnimation *)loopFrom:(id)from to:(id)to key:(NSString *)keyPath duration:(NSTimeInterval)duration ease:(BOOL)ease {
    CABasicAnimation *animation = [CABasicAnimation animationWithKeyPath:keyPath];
    animation.fromValue = from;
    animation.toValue = to;
    animation.duration = duration;
    animation.autoreverses = ease;
    animation.repeatCount = HUGE_VALF;
    animation.timingFunction = [CAMediaTimingFunction functionWithName:ease ? kCAMediaTimingFunctionEaseInEaseOut : kCAMediaTimingFunctionLinear];
    return animation;
}

// Everything that moves. One breath is `pace` seconds.
- (void)restartAnimations {
    for (CALayer *layer in [self animatedLayers]) {
        [layer removeAllAnimations];
    }
    BOOL music = self.kind == RelayGlowKindMusic;
    BOOL reduced = NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion;
    NSTimeInterval pace = music ? 1.7 : ([self.actor isEqualToString:@"you"] ? 0.8 : 1.2);
    BOOL line = [self.style isEqualToString:@"line"];
    self.halo.opacity = 0.7;
    self.outline.opacity = 0.95;
    self.outline.lineWidth = line ? 1.6 : 3;
    if (reduced) {
        for (CAShapeLayer *spark in self.sparks) spark.hidden = YES;
        return;
    }

    if (line) {
        // The quiet look: one thin line on the notch edge that breathes slowly. No halo, no sparks.
        [self.outline addAnimation:[self loopFrom:@0.55 to:@0.95 key:@"opacity" duration:pace * 1.6 ease:YES] forKey:@"breathe"];
        [self.outline addAnimation:[self loopFrom:@3 to:@9 key:@"shadowRadius" duration:pace * 1.6 ease:YES] forKey:@"swell"];
        return;
    }

    [self.halo addAnimation:[self loopFrom:@0.35 to:@0.95 key:@"opacity" duration:pace ease:YES] forKey:@"breathe"];
    [self.halo addAnimation:[self loopFrom:@14 to:@36 key:@"shadowRadius" duration:pace ease:YES] forKey:@"swell"];
    [self.outline addAnimation:[self loopFrom:@8 to:@22 key:@"shadowRadius" duration:pace ease:YES] forKey:@"swell"];

    // Sparks circle the notch (only in the "sparks" style). Music uses two; agents use one per agent, the active one longer.
    if (![self.style isEqualToString:@"sparks"]) return;
    NSInteger count = music ? 2 : SparkCount;
    NSTimeInterval lap = pace * 2.4;
    NSArray *roles = @[ @"observer", @"builder", @"reviewer" ];
    for (NSInteger i = 0; i < count; i++) {
        BOOL active = music || [self.actor isEqualToString:roles[i]] || [self.actor isEqualToString:@"you"];
        CGFloat length = active ? 0.24 : 0.1;
        CAShapeLayer *spark = self.sparks[i];
        spark.strokeStart = 0;
        spark.strokeEnd = length;
        CABasicAnimation *start = [self loopFrom:@0 to:@(1 - length) key:@"strokeStart" duration:lap ease:NO];
        CABasicAnimation *end = [self loopFrom:@(length) to:@1 key:@"strokeEnd" duration:lap ease:NO];
        for (CABasicAnimation *animation in @[ start, end ]) animation.timeOffset = lap * i / count;
        [spark addAnimation:start forKey:@"start"];
        [spark addAnimation:end forKey:@"end"];
    }
}

#pragma mark - Showing

- (void)present:(RelayGlowKind)kind actor:(NSString *)actor color:(NSColor *)color {
    self.wantKind = kind;
    self.wantActor = actor;
    self.wantColor = color;
    if ([self.style isEqualToString:@"off"]) {
        [self dismiss];
        return;
    }
    if (![self prepare]) {
        [self hide];
        return;
    }
    BOOL appeared = !self.visible;
    BOOL restyle = appeared || kind != self.kind || ![(actor ?: @"") isEqualToString:self.actor ?: @""];
    self.kind = kind;
    self.actor = actor;
    self.color = color;
    [CATransaction begin];
    [CATransaction setAnimationDuration:0.7]; // colours slide from one song's colour to the next
    [self applyColors];
    [CATransaction commit];
    if (restyle) [self restartAnimations];
    if (appeared) {
        self.visible = YES;
        [self.window orderFrontRegardless];
        [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
            context.duration = 0.6;
            self.window.animator.alphaValue = 1;
        } completionHandler:nil];
    }
}

- (void)showMusicColor:(NSColor *)color {
    [self present:RelayGlowKindMusic actor:nil color:color];
}

- (void)showAgentActor:(NSString *)actor {
    [self present:RelayGlowKindAgents actor:actor ?: @"relay" color:nil];
}

// A ring of light spreads from the notch edge and fades.
- (void)burst {
    if (!self.visible || NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion) return;
    if ([self.style isEqualToString:@"line"]) return; // the quiet look has no ripple
    CAShapeLayer *ring = [self shapeLayerWithWidth:3];
    ring.frame = self.outline.frame;
    ring.path = self.outline.path;
    ring.strokeColor = self.outline.strokeColor;
    ring.shadowColor = self.outline.shadowColor;
    ring.shadowRadius = 18;
    [self.root addSublayer:ring];
    [CATransaction begin];
    [CATransaction setAnimationDuration:0.9];
    [CATransaction setCompletionBlock:^{ [ring removeFromSuperlayer]; }];
    CABasicAnimation *grow = [CABasicAnimation animationWithKeyPath:@"lineWidth"];
    grow.fromValue = @3;
    grow.toValue = @26;
    CABasicAnimation *fade = [CABasicAnimation animationWithKeyPath:@"opacity"];
    fade.fromValue = @1;
    fade.toValue = @0;
    for (CABasicAnimation *animation in @[ grow, fade ]) {
        animation.duration = 0.9;
        animation.timingFunction = [CAMediaTimingFunction functionWithName:kCAMediaTimingFunctionEaseOut];
        animation.fillMode = kCAFillModeForwards;
        animation.removedOnCompletion = NO;
    }
    [ring addAnimation:grow forKey:@"grow"];
    [ring addAnimation:fade forKey:@"fade"];
    [CATransaction commit];
}

- (void)hide {
    self.wantKind = RelayGlowKindNone;
    self.wantActor = nil;
    self.wantColor = nil;
    [self dismiss];
}

// Fades the light out but remembers what was asked.
- (void)dismiss {
    if (!self.visible) return;
    self.visible = NO;
    self.kind = RelayGlowKindNone;
    self.actor = nil;
    __weak RelayNotchGlow *weakSelf = self;
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.6;
        weakSelf.window.animator.alphaValue = 0;
    } completionHandler:^{
        RelayNotchGlow *strongSelf = weakSelf;
        if (strongSelf && !strongSelf.visible) {
            [strongSelf.window orderOut:nil];
            for (CALayer *layer in [strongSelf animatedLayers]) {
                [layer removeAllAnimations];
            }
        }
    }];
}

- (void)screensChanged {
    if (!self.visible) return;
    self.builtFrame = NSZeroRect; // rebuild for wherever the notch is now
    if (![self prepare]) [self hide];
}

@end
