#import "RelayNotchPanel.h"
#import "RelayNowPlaying.h"
#import "RelayNotchGlow.h"
#import <QuartzCore/QuartzCore.h>
#import <WebKit/WebKit.h>

NSString *const RelayNotchEnabledKey = @"RelayNotchEnabled";

// The panel has three shapes. Heights are measured below the notch band, so they follow the screen's notch.
typedef NS_ENUM(NSInteger, RelayPanelMode) {
    RelayPanelModePill = 0,    // a track just changed: cover, title and a moving equalizer, then it retracts
    RelayPanelModeCompact = 1, // the pointer is on the notch: tabs for Music, Notes and Task
    RelayPanelModeFull = 2,    // double-tap right Command, or something needs the person: adds the Office
};

static const CGFloat PillWidth = 380;
static const CGFloat PillBodyHeight = 46;
static const CGFloat CompactWidth = 440;
static const CGFloat CompactBodyHeight = 170;
static const CGFloat FullWidth = 640;
static const CGFloat FullBodyHeight = 252;
static const CGFloat PanelRadius = 26;
static const NSTimeInterval PillVisibleSeconds = 4.2; // how long a track-change pill stays out
static const NSTimeInterval PillMinGap = 2.0;         // quick skipping does not flash the pill again and again
static const CGFloat TriggerMargin = 55;      // hot zone is the notch plus this much on each side
static const NSTimeInterval ShowDelay = 0.15; // the pointer must rest in the hot zone this long
static const NSTimeInterval HideDelay = 0.45; // grace period after the pointer leaves the panel
static const NSTimeInterval DoneVisibleSeconds = 7.0;
static const NSTimeInterval TapMaxHold = 0.30;    // a Command "tap" is pressed and released within this time
static const NSTimeInterval DoubleTapWindow = 0.45; // two taps within this time toggle the panel
static const CGEventFlags RightCommandMask = 0x00000010; // device-dependent bit for the right Command key
static const CGEventFlags LeftCommandMask = 0x00000008;

// A borderless panel that can take clicks and keys without making Relay the active app.
@interface RelayNotchWindow : NSPanel
@end

@implementation RelayNotchWindow
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)canBecomeMainWindow { return NO; }
// Borderless windows may sit partly above the screen, which the slide-in animation needs.
- (NSRect)constrainFrameRect:(NSRect)frameRect toScreen:(NSScreen *)screen { return frameRect; }
@end

@interface RelayNotchWebView : WKWebView
@end

@implementation RelayNotchWebView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
@end

// Lets the web view hold the message handler without keeping the panel alive in a cycle.
@interface RelayWeakMessageHandler : NSObject <WKScriptMessageHandler>
@property(nonatomic, weak) id<WKScriptMessageHandler> target;
@end

@implementation RelayWeakMessageHandler
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    [self.target userContentController:controller didReceiveScriptMessage:message];
}
@end

@interface RelayNotchPanel () <WKScriptMessageHandler, WKNavigationDelegate>
@property(nonatomic, strong) NSURL *pageURL;
@property(nonatomic, strong) RelayNotchWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, strong) id activity;       // keeps macOS from slowing the pointer watch (App Nap) when Relay is in the background
@property(nonatomic, strong) id mouseMonitor;   // wakes the watch on every pointer move, in any app
@property(nonatomic, strong) NSTimer *showTimer;
@property(nonatomic, strong) NSTimer *hideTimer;
@property(nonatomic, strong) NSTimer *doneTimer;
@property(nonatomic) BOOL shown;
@property(nonatomic) BOOL pinned;   // stays until the pointer has visited and left
@property(nonatomic) BOOL hovered;  // the pointer has been over the panel since it appeared
@property(nonatomic, strong) NSTimer *frameTimer;
@property(nonatomic, strong) NSScreen *screen;
@property(nonatomic) BOOL sticky;   // opened with the keyboard: stays until toggled again
@property(nonatomic) BOOL holding;  // the person is typing a note: do not close because the pointer left
@property(nonatomic, strong) RelayNowPlaying *nowPlaying; // what is playing, shown as a strip in the panel
@property(nonatomic) BOOL commandDown;
@property(nonatomic) BOOL commandTapValid;
@property(nonatomic) CFAbsoluteTime commandPressedAt;
@property(nonatomic) CFAbsoluteTime lastTapAt;
@property(nonatomic) CGFloat progress; // 0: the size of the notch, 1: fully open
@property(nonatomic) RelayPanelMode mode;
@property(nonatomic) NSSize shownSize;  // the size at progress 1 for the current mode (animates between modes)
@property(nonatomic) NSSize contentSize; // what the page is laid out at: the size of the current mode, never animated
@property(nonatomic, strong) NSTimer *sizeTimer;
@property(nonatomic, strong) NSTimer *pillTimer;
@property(nonatomic, copy) NSString *modeView; // the view the page was last asked to show
@property(nonatomic) CFAbsoluteTime lastPillAt;
@property(nonatomic, strong) RelayNotchGlow *glow;       // light around the closed notch
@property(nonatomic, strong) NSTimer *agentTimer;       // asks the engine whether agents are working
@property(nonatomic, copy) NSString *agentActor;        // nil when no task is running
@property(nonatomic, strong) NSColor *musicColor;       // the colour of the cover that is playing
@property(nonatomic, copy) NSString *musicColorSource;  // the artwork that colour came from
@end

@implementation RelayNotchPanel

- (instancetype)initWithPageURL:(NSURL *)pageURL {
    self = [super init];
    if (self) {
        [NSUserDefaults.standardUserDefaults registerDefaults:@{RelayNotchEnabledKey: @YES}];
        _pageURL = pageURL;
        [self buildWindow];
        [self installMonitors];
        _nowPlaying = [[RelayNowPlaying alloc] init];
        __weak RelayNotchPanel *weakSelf = self;
        _nowPlaying.handler = ^(NSDictionary *state) { [weakSelf pushNowPlaying:state]; };
        _nowPlaying.trackChangeHandler = ^(NSDictionary *state) {
            [weakSelf.glow burst];
            [weakSelf showTrackPill];
        };
        _glow = [[RelayNotchGlow alloc] init];
        if (self.enabled) [self startAmbient];
    }
    return self;
}

- (void)dealloc {
    [self removeMonitors];
}

#pragma mark - Setting

- (BOOL)enabled {
    return [NSUserDefaults.standardUserDefaults boolForKey:RelayNotchEnabledKey];
}

- (void)setEnabled:(BOOL)enabled {
    [NSUserDefaults.standardUserDefaults setBool:enabled forKey:RelayNotchEnabledKey];
    if (enabled) {
        [self startAmbient];
    } else {
        [self hideAnimated:YES];
        [self stopAmbient];
    }
}

#pragma mark - Light around the notch

static NSColor *RGB(CGFloat r, CGFloat g, CGFloat b) { return [NSColor colorWithSRGBRed:r / 255 green:g / 255 blue:b / 255 alpha:1]; }

// The colour of the cover: vivid pixels count most, and dark covers are lifted so the light is visible.
static NSColor *DominantColor(NSString *dataURL) {
    NSRange comma = [dataURL rangeOfString:@","];
    if (comma.location == NSNotFound) return nil;
    NSData *data = [[NSData alloc] initWithBase64EncodedString:[dataURL substringFromIndex:comma.location + 1]
                                                       options:NSDataBase64DecodingIgnoreUnknownCharacters];
    NSImage *image = data ? [[NSImage alloc] initWithData:data] : nil;
    CGImageRef cg = image ? [image CGImageForProposedRect:NULL context:nil hints:nil] : NULL;
    if (!cg) return nil;
    uint8_t pixels[16 * 16 * 4] = {0};
    CGColorSpaceRef space = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(pixels, 16, 16, 8, 16 * 4, space, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(space);
    if (!context) return nil;
    CGContextDrawImage(context, CGRectMake(0, 0, 16, 16), cg);
    CGContextRelease(context);
    double r = 0, g = 0, b = 0, weight = 0;
    for (int i = 0; i < 16 * 16 * 4; i += 4) {
        double high = MAX(pixels[i], MAX(pixels[i + 1], pixels[i + 2]));
        double low = MIN(pixels[i], MIN(pixels[i + 1], pixels[i + 2]));
        double saturation = high > 0 ? (high - low) / high : 0;
        double w = saturation * saturation * (high / 255) + 0.01;
        r += pixels[i] * w;
        g += pixels[i + 1] * w;
        b += pixels[i + 2] * w;
        weight += w;
    }
    r /= weight; g /= weight; b /= weight;
    double top = MAX(r, MAX(g, b));
    if (top <= 0) return nil;
    double lift = top < 170 ? 170 / top : 1;
    return RGB(MIN(255, r * lift), MIN(255, g * lift), MIN(255, b * lift));
}

- (void)startAmbient {
    [self.nowPlaying start];
    if (!self.agentTimer) {
        __weak RelayNotchPanel *weakSelf = self;
        NSTimer *timer = [NSTimer timerWithTimeInterval:2.0 repeats:YES block:^(NSTimer *tick) { [weakSelf pollAgents]; }];
        timer.tolerance = 0.5;
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
        self.agentTimer = timer;
    }
    [self pollAgents];
}

- (void)stopAmbient {
    [self.agentTimer invalidate];
    self.agentTimer = nil;
    self.agentActor = nil;
    [self.nowPlaying stop];
    [self.glow hide];
}

// Asks the local engine (the same feed the panel page uses) whether an agent is working right now.
- (void)pollAgents {
    NSURL *url = [NSURL URLWithString:@"/api/notch" relativeToURL:self.pageURL].absoluteURL;
    if (!url) return;
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    request.timeoutInterval = 3;
    request.cachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
    __weak RelayNotchPanel *weakSelf = self;
    [[NSURLSession.sharedSession dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSString *actor = nil;
        id parsed = (data && !error) ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        NSDictionary *run = [parsed isKindOfClass:NSDictionary.class] && [parsed[@"run"] isKindOfClass:NSDictionary.class] ? parsed[@"run"] : nil;
        if (run && [run[@"running"] boolValue] && ![run[@"paused"] boolValue]) {
            actor = [run[@"actor"] isKindOfClass:NSString.class] ? run[@"actor"] : @"relay";
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            RelayNotchPanel *strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.enabled) return;
            if ((strongSelf.agentActor == nil && actor == nil) || [strongSelf.agentActor isEqualToString:actor]) return;
            strongSelf.agentActor = actor;
            [strongSelf refreshGlow];
            if (actor) [strongSelf.glow burst]; // a new agent took over
        });
    }] resume];
}

// Agents at work come first (their colour), then music (the cover's colour). Nothing: no light.
- (void)refreshGlow {
    if (!self.enabled) {
        [self.glow hide];
        return;
    }
    if (self.agentActor) {
        [self.glow showAgentActor:self.agentActor];
    } else if ([self.nowPlaying.state[@"playing"] boolValue]) {
        [self.glow showMusicColor:self.musicColor ?: RGB(79, 181, 148)];
    } else {
        [self.glow hide];
    }
}

// Sends what is playing to the panel page. nil clears the music strip.
- (void)pushNowPlaying:(NSDictionary *)state {
    NSString *artwork = [state[@"artwork"] isKindOfClass:NSString.class] ? state[@"artwork"] : nil;
    if (![artwork isEqualToString:self.musicColorSource ?: @""]) {
        self.musicColorSource = artwork;
        self.musicColor = artwork ? DominantColor(artwork) : nil;
    }
    [self refreshGlow];
    NSString *script = @"if (!window.relayNowPlaying) return 'page has no handler yet';"
                        "window.relayNowPlaying(state);"
                        "return 'strip ' + (document.getElementById('panel').dataset.music ? 'shown' : 'hidden');";
    [self.webView callAsyncJavaScript:script
                            arguments:@{ @"state": state ?: NSNull.null }
                              inFrame:nil
                       inContentWorld:WKContentWorld.pageWorld
                    completionHandler:^(id result, NSError *error) {
        [RelayNowPlaying log:[NSString stringWithFormat:@"page answered: %@", error ? [NSString stringWithFormat:@"FAILED %@", error] : result]];
    }];
}

#pragma mark - Window

- (void)buildWindow {
    _mode = RelayPanelModeCompact;
    _shownSize = NSMakeSize(CompactWidth, 26 + CompactBodyHeight);
    _contentSize = _shownSize;
    NSRect frame = NSMakeRect(0, 0, _shownSize.width, _shownSize.height);
    RelayNotchWindow *window = [[RelayNotchWindow alloc] initWithContentRect:frame
                                                                   styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                                     backing:NSBackingStoreBuffered
                                                                       defer:NO];
    window.releasedWhenClosed = NO;
    window.level = NSMainMenuWindowLevel + 2;
    window.opaque = NO;
    window.backgroundColor = NSColor.clearColor;
    // The system shadow also draws a thin light rim along the top edge; the panel does not need either.
    window.hasShadow = NO;
    window.hidesOnDeactivate = NO;
    window.canHide = NO; // the panel stays even if Relay is hidden with Command-H
    window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                NSWindowCollectionBehaviorStationary |
                                NSWindowCollectionBehaviorFullScreenAuxiliary |
                                NSWindowCollectionBehaviorIgnoresCycle;

    // Round only the bottom corners so the panel looks like it hangs from the screen edge.
    NSView *container = [[NSView alloc] initWithFrame:frame];
    container.wantsLayer = YES;
    container.layer.backgroundColor = NSColor.blackColor.CGColor; // the same black as the notch itself
    container.layer.cornerRadius = PanelRadius;
    container.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMaxXMinYCorner;
    container.layer.masksToBounds = YES;
    window.contentView = container;

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    RelayWeakMessageHandler *handler = [[RelayWeakMessageHandler alloc] init];
    handler.target = self;
    [configuration.userContentController addScriptMessageHandler:handler name:@"relayPanel"];
    WKWebView *webView = [[RelayNotchWebView alloc] initWithFrame:container.bounds configuration:configuration];
    // The page keeps the size of the current mode and stays pinned to the top while the window grows out of the notch.
    // layoutWebView places it on every frame, so it must not also resize itself.
    webView.autoresizingMask = NSViewNotSizable;
    webView.navigationDelegate = self;
    [webView setValue:@NO forKey:@"drawsBackground"];
    [container addSubview:webView];
    self.webView = webView;
    self.window = window;

    [webView loadRequest:[NSURLRequest requestWithURL:self.pageURL]];
}

- (NSScreen *)screenForPoint:(NSPoint)point {
    for (NSScreen *screen in NSScreen.screens) {
        // The pointer can sit exactly on the top edge, which NSPointInRect would treat as outside.
        NSRect frame = screen.frame;
        if (point.x >= NSMinX(frame) && point.x <= NSMaxX(frame) && point.y >= NSMinY(frame) && point.y <= NSMaxY(frame)) return screen;
    }
    return nil;
}

// The size of the physical notch, or a similar pill on Macs without one.
- (NSSize)notchSizeForScreen:(NSScreen *)screen {
    CGFloat width = 180, height = 26;
    if (@available(macOS 12.0, *)) {
        if (screen.safeAreaInsets.top > 0) {
            height = screen.safeAreaInsets.top;
            NSRect left = screen.auxiliaryTopLeftArea, right = screen.auxiliaryTopRightArea;
            if (!NSIsEmptyRect(left) && !NSIsEmptyRect(right) && NSMinX(right) > NSMaxX(left)) {
                width = NSMinX(right) - NSMaxX(left);
            }
        }
    }
    return NSMakeSize(width, height);
}

// progress 0 is exactly the notch; 1 is the open panel hanging from the top edge.
- (void)applyProgress:(CGFloat)progress {
    self.progress = progress;
    NSScreen *screen = self.screen ?: NSScreen.mainScreen ?: NSScreen.screens.firstObject;
    if (!screen) return;
    NSRect area = screen.frame;
    NSSize notch = [self notchSizeForScreen:screen];
    CGFloat amount = MAX(0, progress);
    NSSize open = self.shownSize;
    CGFloat width = notch.width + (MAX(open.width, notch.width) - notch.width) * amount;
    CGFloat height = notch.height + (MAX(open.height, notch.height) - notch.height) * amount;
    NSRect frame = NSMakeRect(NSMidX(area) - width / 2, NSMaxY(area) - height, width, height);
    [self.window setFrame:frame display:YES];
    [self layoutWebView];
    CGFloat settled = MIN(1, amount);
    ((NSView *)self.window.contentView).layer.cornerRadius = 9 + (PanelRadius - 9) * settled;
    // The content appears once the panel is mostly open and goes first when it closes.
    self.webView.alphaValue = MIN(1, MAX(0, (settled - 0.5) / 0.4));
}

// The page always has the full size of the current mode, centered and pinned to the top of the clipped window.
- (void)layoutWebView {
    NSRect bounds = ((NSView *)self.window.contentView).bounds;
    NSSize size = self.contentSize; // the page is not re-laid-out on every frame of a resize
    NSRect frame = NSMakeRect(round((NSWidth(bounds) - size.width) / 2), NSHeight(bounds) - size.height, size.width, size.height);
    if (!NSEqualRects(self.webView.frame, frame)) self.webView.frame = frame;
}

- (NSSize)sizeForMode:(RelayPanelMode)mode screen:(NSScreen *)screen {
    CGFloat band = [self notchSizeForScreen:screen].height;
    switch (mode) {
        case RelayPanelModePill: return NSMakeSize(PillWidth, band + PillBodyHeight);
        case RelayPanelModeCompact: return NSMakeSize(CompactWidth, band + CompactBodyHeight);
        case RelayPanelModeFull: return NSMakeSize(FullWidth, band + FullBodyHeight);
    }
    return NSMakeSize(CompactWidth, band + CompactBodyHeight);
}

- (NSScreen *)activeScreen {
    return self.screen ?: NSScreen.mainScreen ?: NSScreen.screens.firstObject;
}

// Tells the page which shape it has, how big the notch is, and optionally which view to show.
- (void)pushMode {
    NSScreen *screen = [self activeScreen];
    if (!screen) return;
    NSSize notch = [self notchSizeForScreen:screen];
    NSArray *names = @[ @"pill", @"compact", @"full" ];
    NSDictionary *info = @{ @"mode": names[self.mode], @"notchWidth": @(round(notch.width)), @"notchHeight": @(round(notch.height)),
                            @"view": self.modeView ?: NSNull.null };
    NSString *script = @"if (!window.relayPanelMode) return 'page has no mode handler yet'; window.relayPanelMode(info); return 'ok';";
    [self.webView callAsyncJavaScript:script
                            arguments:@{ @"info": info }
                              inFrame:nil
                       inContentWorld:WKContentWorld.pageWorld
                    completionHandler:^(id result, NSError *error) {
        if (error || ![result isEqual:@"ok"]) [RelayNowPlaying log:[NSString stringWithFormat:@"mode push: %@", error ? [NSString stringWithFormat:@"FAILED %@", error] : result]];
    }];
}

// Changes the shape. A panel that is already open grows or shrinks smoothly; one that is opening just aims at the new size.
- (void)changeMode:(RelayPanelMode)mode view:(NSString *)view {
    BOOL changed = mode != self.mode;
    self.mode = mode;
    self.modeView = view;
    NSScreen *screen = [self activeScreen];
    if (!screen) return;
    NSSize target = [self sizeForMode:mode screen:screen];
    self.contentSize = target;
    [self pushMode];
    BOOL settled = self.shown && self.progress >= 1 && !self.frameTimer;
    if (settled && changed) {
        [self animateSizeTo:target duration:0.32];
        return;
    }
    [self.sizeTimer invalidate];
    self.sizeTimer = nil;
    self.shownSize = target;
    if (self.shown && !self.frameTimer) [self applyProgress:self.progress];
}

- (void)animateSizeTo:(NSSize)target duration:(NSTimeInterval)duration {
    [self.sizeTimer invalidate];
    self.sizeTimer = nil;
    NSSize start = self.shownSize;
    if (duration <= 0 || NSEqualSizes(start, target)) {
        self.shownSize = target;
        [self applyProgress:self.progress];
        return;
    }
    NSDate *began = [NSDate date];
    __weak RelayNotchPanel *weakSelf = self;
    NSTimer *timer = [NSTimer timerWithTimeInterval:1.0 / 120 repeats:YES block:^(NSTimer *tick) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) { [tick invalidate]; return; }
        CGFloat t = MIN(1, -[began timeIntervalSinceNow] / duration);
        CGFloat eased = 1 - pow(1 - t, 3);
        strongSelf.shownSize = NSMakeSize(start.width + (target.width - start.width) * eased,
                                          start.height + (target.height - start.height) * eased);
        if (t >= 1) {
            [tick invalidate];
            strongSelf.sizeTimer = nil;
            strongSelf.shownSize = target;
        }
        [strongSelf applyProgress:strongSelf.progress];
    }];
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    self.sizeTimer = timer;
}

- (void)animateToProgress:(CGFloat)target duration:(NSTimeInterval)duration completion:(void (^)(void))completion {
    [self.frameTimer invalidate];
    CGFloat start = self.progress;
    if (duration <= 0 || start == target) {
        [self applyProgress:target];
        if (completion) completion();
        return;
    }
    NSDate *began = [NSDate date];
    __weak RelayNotchPanel *weakSelf = self;
    NSTimer *timer = [NSTimer timerWithTimeInterval:1.0 / 120 repeats:YES block:^(NSTimer *tick) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) { [tick invalidate]; return; }
        CGFloat t = MIN(1, -[began timeIntervalSinceNow] / duration);
        // No overshoot: opening eases out and closing eases in and out, so the motion stays smooth.
        CGFloat eased = target > start ? 1 - pow(1 - t, 4) : t * t * (3 - 2 * t);
        [strongSelf applyProgress:start + (target - start) * eased];
        if (t >= 1) {
            [tick invalidate];
            strongSelf.frameTimer = nil;
            [strongSelf applyProgress:target];
            if (completion) completion();
        }
    }];
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    self.frameTimer = timer;
}

#pragma mark - Showing and hiding

// Opens in the given shape, or grows an open panel to it. A panel never shrinks because something else asked.
- (void)showOnScreen:(NSScreen *)screen mode:(RelayPanelMode)mode view:(NSString *)view {
    if (!screen) screen = NSScreen.mainScreen ?: NSScreen.screens.firstObject;
    if (!screen) return;
    [self cancelTimer:&_hideTimer];
    self.screen = screen;
    if (!self.shown) {
        self.shown = YES;
        self.hovered = NO;
        [self.sizeTimer invalidate];
        self.sizeTimer = nil;
        self.progress = 0;
        [self changeMode:mode view:view];
        [self applyProgress:0];
        [self.window orderFrontRegardless];
        [self animateToProgress:1 duration:mode == RelayPanelModePill ? 0.4 : 0.5 completion:nil];
        return;
    }
    if (mode > self.mode || (view && mode == self.mode && !self.holding)) [self changeMode:MAX(mode, self.mode) view:view];
    if (self.progress < 1 && !self.frameTimer) {
        [self animateToProgress:1 duration:0.3 completion:nil];
    } else if (!self.frameTimer && !self.sizeTimer) {
        [self applyProgress:1];
    }
}

- (void)hideAnimated:(BOOL)animated {
    [self cancelTimer:&_showTimer];
    [self cancelTimer:&_hideTimer];
    [self cancelTimer:&_doneTimer];
    [self cancelTimer:&_pillTimer];
    [self.sizeTimer invalidate];
    self.sizeTimer = nil;
    self.pinned = NO;
    self.sticky = NO;
    self.hovered = NO;
    self.holding = NO;
    if (!self.shown) return;
    self.shown = NO;
    __weak RelayNotchPanel *weakSelf = self;
    [self animateToProgress:0 duration:animated ? 0.32 : 0 completion:^{
        // A new show request may have started while this was running.
        RelayNotchPanel *strongSelf = weakSelf;
        if (strongSelf && !strongSelf.shown) [strongSelf.window orderOut:nil];
    }];
}

// Double-tap right Command: open the full panel on the Office, or close it when it is already full.
- (void)toggle {
    if (self.shown && self.mode == RelayPanelModeFull) {
        [self hideAnimated:YES];
        return;
    }
    [self cancelTimer:&_doneTimer];
    [self cancelTimer:&_pillTimer];
    self.pinned = YES;
    self.sticky = YES;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation] mode:RelayPanelModeFull view:@"office"];
    // Opened on purpose from the keyboard: take the keys so Escape works at once.
    [self.window makeKeyWindow];
    [self.window makeFirstResponder:self.webView];
}

// Something needs the person (a plan to approve): the full panel, kept until they have looked at it.
- (void)showPinned {
    if (!self.enabled) return;
    [self cancelTimer:&_doneTimer];
    [self cancelTimer:&_pillTimer];
    self.pinned = YES;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation] mode:RelayPanelModeFull view:nil];
}

// A task finished or failed: peek in for a few seconds, then leave unless the pointer is on the panel.
- (void)peek {
    if (!self.enabled) return;
    [self cancelTimer:&_pillTimer];
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation] mode:RelayPanelModeCompact view:@"task"];
    [self cancelTimer:&_doneTimer];
    __weak RelayNotchPanel *weakSelf = self;
    self.doneTimer = [NSTimer scheduledTimerWithTimeInterval:DoneVisibleSeconds repeats:NO block:^(NSTimer *timer) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf || strongSelf.pinned || strongSelf.holding) return;
        if (![strongSelf pointerIsNearPanel]) [strongSelf hideAnimated:YES];
    }];
}

// The track changed: the notch grows into a small pill for a few seconds. It never interrupts an open panel.
- (void)showTrackPill {
    if (!self.enabled || self.shown) return;
    CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
    if (now - self.lastPillAt < PillMinGap) return;
    self.lastPillAt = now;
    self.pinned = NO;
    self.sticky = NO;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation] mode:RelayPanelModePill view:nil];
    [self cancelTimer:&_pillTimer];
    __weak RelayNotchPanel *weakSelf = self;
    self.pillTimer = [NSTimer scheduledTimerWithTimeInterval:PillVisibleSeconds repeats:NO block:^(NSTimer *timer) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) return;
        strongSelf.pillTimer = nil;
        if (strongSelf.shown && strongSelf.mode == RelayPanelModePill) [strongSelf hideAnimated:YES];
    }];
}

#pragma mark - Pointer tracking

// The pointer and modifier keys are read 40 times a second. This works in every app and Space,
// needs no special permission, and also catches the very top pixel row that event monitors can miss.
- (void)installMonitors {
    if (self.pollTimer) return;
    __weak RelayNotchPanel *weakSelf = self;
    // Without this, macOS slows timers right down once Relay is not the front app, and the hover and the
    // double Command tap stop responding anywhere except in Relay itself.
    self.activity = [NSProcessInfo.processInfo beginActivityWithOptions:(NSActivityUserInitiated | NSActivityLatencyCritical)
                                                                  reason:@"Watching the pointer and the Command key for the notch panel"];
    // Pointer events from other apps need no special permission, and they also wake the app if it was napping.
    self.mouseMonitor = [NSEvent addGlobalMonitorForEventsMatchingMask:NSEventMaskMouseMoved
                                                               handler:^(NSEvent *event) { [weakSelf pointerMoved]; }];
    NSTimer *timer = [NSTimer timerWithTimeInterval:0.025 repeats:YES block:^(NSTimer *tick) {
        [weakSelf pointerMoved];
    }];
    timer.tolerance = 0.005;
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    self.pollTimer = timer;
}

- (void)removeMonitors {
    if (self.mouseMonitor) [NSEvent removeMonitor:self.mouseMonitor];
    self.mouseMonitor = nil;
    if (self.activity) [NSProcessInfo.processInfo endActivity:self.activity];
    self.activity = nil;
    [self.pollTimer invalidate];
    self.pollTimer = nil;
    [self cancelTimer:&_showTimer];
}

- (BOOL)pointerIsNearPanel {
    return NSPointInRect(NSEvent.mouseLocation, NSInsetRect(self.window.frame, -14, -14));
}

- (BOOL)pointerIsInHotZone {
    NSPoint point = NSEvent.mouseLocation;
    NSScreen *screen = [self screenForPoint:point];
    if (!screen) return NO;
    NSRect area = screen.frame;
    // The hot zone is the whole menu bar band around the notch, not only the top pixel row.
    NSSize notch = [self notchSizeForScreen:screen];
    CGFloat half = notch.width / 2 + TriggerMargin;
    return point.y >= NSMaxY(area) - (notch.height + 4) && fabs(point.x - NSMidX(area)) <= half;
}

// Double-tap the right Command key to open or close the panel. The key state is read directly,
// so this works in every app without asking for Input Monitoring or Accessibility access.
- (void)checkCommandTaps {
    CGEventFlags flags = CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState);
    CGEventFlags others = kCGEventFlagMaskShift | kCGEventFlagMaskControl | kCGEventFlagMaskAlternate;
    BOOL rightDown = (flags & RightCommandMask) != 0;
    BOOL clean = rightDown && !(flags & LeftCommandMask) && !(flags & others);
    CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();

    if (rightDown && !self.commandDown) {
        self.commandDown = YES;
        self.commandPressedAt = now;
        self.commandTapValid = clean;
        return;
    }
    if (rightDown) {
        if (!clean) self.commandTapValid = NO;
        return;
    }
    if (!self.commandDown) return;

    // Released.
    self.commandDown = NO;
    CFTimeInterval held = now - self.commandPressedAt;
    // Command with a key or a click (for example Command-C) is a shortcut, not a tap.
    CFTimeInterval sinceKey = CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGEventKeyDown);
    CFTimeInterval sinceClick = CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGEventLeftMouseDown);
    BOOL usedWithOtherInput = sinceKey < held + 0.05 || sinceClick < held + 0.05;
    if (!self.commandTapValid || held > TapMaxHold || usedWithOtherInput) {
        self.lastTapAt = 0;
        return;
    }
    if (self.lastTapAt > 0 && now - self.lastTapAt <= DoubleTapWindow) {
        self.lastTapAt = 0;
        [self toggle];
    } else {
        self.lastTapAt = now;
    }
}

- (void)pointerMoved {
    [self checkCommandTaps];
    if (!self.enabled) return;
    if (self.shown) {
        if ([self pointerIsNearPanel]) {
            self.hovered = YES;
            [self cancelTimer:&_hideTimer];
            if (self.mode == RelayPanelModePill) {
                // The pointer reached the pill: it becomes the compact panel, on the music.
                [self cancelTimer:&_pillTimer];
                [self changeMode:RelayPanelModeCompact view:@"music"];
            }
            return;
        }
        if (self.mode == RelayPanelModePill) return; // retracts by its own timer
        if (self.holding) {
            [self cancelTimer:&_hideTimer];
            return;
        }
        // Opened with the keyboard: it stays until the same shortcut, Escape, or Open Relay.
        if (self.sticky) return;
        // Opened because something needs the person: wait until they have looked at it.
        if (self.pinned && !self.hovered) return;
        [self scheduleHide];
        return;
    }
    // Ignore the pointer while dragging, for example when moving a window to the top of the screen.
    if ([self pointerIsInHotZone] && NSEvent.pressedMouseButtons == 0) {
        [self scheduleShow];
    } else {
        [self cancelTimer:&_showTimer];
    }
}

- (void)scheduleShow {
    if (self.showTimer) return;
    __weak RelayNotchPanel *weakSelf = self;
    self.showTimer = [NSTimer scheduledTimerWithTimeInterval:ShowDelay repeats:NO block:^(NSTimer *timer) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) return;
        strongSelf.showTimer = nil;
        if (strongSelf.enabled && !strongSelf.shown && [strongSelf pointerIsInHotZone]) {
            strongSelf.pinned = NO;
            [strongSelf showOnScreen:[strongSelf screenForPoint:NSEvent.mouseLocation] mode:RelayPanelModeCompact view:nil];
        }
    }];
}

- (void)scheduleHide {
    if (self.hideTimer) return;
    __weak RelayNotchPanel *weakSelf = self;
    self.hideTimer = [NSTimer scheduledTimerWithTimeInterval:HideDelay repeats:NO block:^(NSTimer *timer) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) return;
        strongSelf.hideTimer = nil;
        if (!strongSelf.holding && ![strongSelf pointerIsNearPanel]) [strongSelf hideAnimated:YES];
    }];
}

- (void)cancelTimer:(NSTimer *__strong *)timer {
    [*timer invalidate];
    *timer = nil;
}

#pragma mark - Messages from the panel page

- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    // Only Relay's own page, served by the local engine, may talk to the app.
    NSURL *origin = message.frameInfo.request.URL;
    if (!message.frameInfo.isMainFrame ||
        ![origin.host isEqualToString:self.pageURL.host] ||
        ![origin.port isEqualToNumber:self.pageURL.port]) return;
    if (![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *body = message.body;
    NSString *type = [body[@"type"] isKindOfClass:NSString.class] ? body[@"type"] : @"";

    if ([type isEqualToString:@"open"]) {
        [self.delegate notchPanelRequestsOpenRelay];
        [self hideAnimated:YES];
    } else if ([type isEqualToString:@"hide"]) {
        [self hideAnimated:YES];
    } else if ([type isEqualToString:@"attention"]) {
        if ([body[@"keep"] boolValue]) [self showPinned];
        else [self peek];
    } else if ([type isEqualToString:@"ready"]) {
        // The page has just loaded and can now show its shape and what is playing.
        [RelayNowPlaying log:@"page is ready"];
        if (self.shown) [self pushMode];
        if (self.nowPlaying.state) [self pushNowPlaying:self.nowPlaying.state];
    } else if ([type isEqualToString:@"expand"]) {
        // The small panel needs room: a plan to approve, or the person pressed the Office tab.
        NSString *view = [body[@"view"] isEqual:@"office"] ? @"office" : nil;
        if (self.shown) {
            [self cancelTimer:&_pillTimer];
            [self showOnScreen:self.screen mode:RelayPanelModeFull view:view];
            // Pressed on purpose: take the keys so Escape closes it. It still closes when the pointer leaves.
            if (view) {
                [self.window makeKeyWindow];
                [self.window makeFirstResponder:self.webView];
            }
        }
    } else if ([type isEqualToString:@"shrink"]) {
        // The person left the Office (or the plan) for a view that fits the small panel.
        if (self.shown && self.mode == RelayPanelModeFull) {
            [self cancelTimer:&_doneTimer];
            self.sticky = NO;
            self.pinned = NO;
            self.hovered = YES;
            [self changeMode:RelayPanelModeCompact view:nil];
        }
    } else if ([type isEqualToString:@"media"]) {
        [self.nowPlaying sendCommand:body[@"command"]];
    } else if ([type isEqualToString:@"hold"]) {
        // The note field has the keyboard: keep the panel open until typing stops or Escape.
        self.holding = [body[@"on"] boolValue];
        if (self.holding) {
            [self cancelTimer:&_hideTimer];
            [self.window makeKeyWindow];
        }
    } else if ([type isEqualToString:@"settle"]) {
        // The question was answered somewhere else, so the panel no longer needs to stay.
        self.pinned = NO;
        if (self.shown && ![self pointerIsNearPanel]) [self scheduleHide];
    }
}

#pragma mark - WKNavigationDelegate

- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = action.request.URL;
    BOOL local = [url.host isEqualToString:self.pageURL.host] && [url.port isEqualToNumber:self.pageURL.port];
    decisionHandler(local ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    // The page may have been reloaded while open or while something was playing.
    if (self.shown) [self pushMode];
    if (self.nowPlaying.state) [self pushNowPlaying:self.nowPlaying.state];
}

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [webView reload];
}

@end
