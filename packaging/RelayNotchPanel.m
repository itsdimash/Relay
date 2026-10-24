#import "RelayNotchPanel.h"
#import <QuartzCore/QuartzCore.h>
#import <WebKit/WebKit.h>

NSString *const RelayNotchEnabledKey = @"RelayNotchEnabled";

static const CGFloat PanelWidth = 640;
static const CGFloat PanelHeight = 284;
static const CGFloat PanelRadius = 28;
static const CGFloat TriggerMargin = 40;      // hot zone is the notch plus this much on each side
static const CGFloat TriggerDepth = 3;        // how close to the very top edge the pointer must be
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
@property(nonatomic, strong) NSTimer *showTimer;
@property(nonatomic, strong) NSTimer *hideTimer;
@property(nonatomic, strong) NSTimer *doneTimer;
@property(nonatomic) BOOL shown;
@property(nonatomic) BOOL pinned;   // stays until the pointer has visited and left
@property(nonatomic) BOOL hovered;  // the pointer has been over the panel since it appeared
@property(nonatomic, strong) NSTimer *frameTimer;
@property(nonatomic, strong) NSScreen *screen;
@property(nonatomic) BOOL sticky;   // opened with the keyboard: stays until toggled again
@property(nonatomic) BOOL commandDown;
@property(nonatomic) BOOL commandTapValid;
@property(nonatomic) CFAbsoluteTime commandPressedAt;
@property(nonatomic) CFAbsoluteTime lastTapAt;
@property(nonatomic) CGFloat progress; // 0: the size of the notch, 1: fully open
@end

@implementation RelayNotchPanel

- (instancetype)initWithPageURL:(NSURL *)pageURL {
    self = [super init];
    if (self) {
        [NSUserDefaults.standardUserDefaults registerDefaults:@{RelayNotchEnabledKey: @YES}];
        _pageURL = pageURL;
        [self buildWindow];
        [self installMonitors];
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
    if (!enabled) [self hideAnimated:YES];
}

#pragma mark - Window

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, PanelWidth, PanelHeight);
    RelayNotchWindow *window = [[RelayNotchWindow alloc] initWithContentRect:frame
                                                                   styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                                     backing:NSBackingStoreBuffered
                                                                       defer:NO];
    window.releasedWhenClosed = NO;
    window.level = NSMainMenuWindowLevel + 2;
    window.opaque = NO;
    window.backgroundColor = NSColor.clearColor;
    window.hasShadow = YES;
    window.hidesOnDeactivate = NO;
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
    // The page keeps its full size and stays pinned to the top while the window grows out of the notch.
    webView.autoresizingMask = NSViewMinXMargin | NSViewMaxXMargin | NSViewMinYMargin;
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
    CGFloat width = notch.width + (PanelWidth - notch.width) * amount;
    CGFloat height = notch.height + (PanelHeight - notch.height) * amount;
    NSRect frame = NSMakeRect(NSMidX(area) - width / 2, NSMaxY(area) - height, width, height);
    [self.window setFrame:frame display:YES];
    CGFloat settled = MIN(1, amount);
    ((NSView *)self.window.contentView).layer.cornerRadius = 9 + (PanelRadius - 9) * settled;
    // The content appears once the panel is mostly open and goes first when it closes.
    self.webView.alphaValue = MIN(1, MAX(0, (settled - 0.5) / 0.4));
    [self.window invalidateShadow];
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
    NSTimer *timer = [NSTimer timerWithTimeInterval:1.0 / 90 repeats:YES block:^(NSTimer *tick) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf) { [tick invalidate]; return; }
        CGFloat t = MIN(1, -[began timeIntervalSinceNow] / duration);
        CGFloat eased;
        if (target > start) {
            // Opening: fast start, a small overshoot, then settle.
            CGFloat u = t - 1;
            eased = 1 + 2.2 * u * u * u + 1.2 * u * u;
        } else {
            eased = t * t * t;
        }
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

- (void)showOnScreen:(NSScreen *)screen {
    if (!screen) screen = NSScreen.mainScreen ?: NSScreen.screens.firstObject;
    if (!screen) return;
    [self cancelTimer:&_hideTimer];
    self.screen = screen;
    if (!self.shown) {
        self.shown = YES;
        self.hovered = NO;
        [self applyProgress:0];
        [self.window orderFrontRegardless];
        [self animateToProgress:1 duration:0.45 completion:nil];
    } else if (self.progress < 1 && !self.frameTimer) {
        [self animateToProgress:1 duration:0.3 completion:nil];
    } else if (!self.frameTimer) {
        [self applyProgress:1];
    }
}

- (void)hideAnimated:(BOOL)animated {
    [self cancelTimer:&_showTimer];
    [self cancelTimer:&_hideTimer];
    [self cancelTimer:&_doneTimer];
    self.pinned = NO;
    self.sticky = NO;
    self.hovered = NO;
    if (!self.shown) return;
    self.shown = NO;
    __weak RelayNotchPanel *weakSelf = self;
    [self animateToProgress:0 duration:animated ? 0.28 : 0 completion:^{
        // A new show request may have started while this was running.
        RelayNotchPanel *strongSelf = weakSelf;
        if (strongSelf && !strongSelf.shown) [strongSelf.window orderOut:nil];
    }];
}

- (void)toggle {
    if (self.shown) {
        [self hideAnimated:YES];
        return;
    }
    [self cancelTimer:&_doneTimer];
    self.pinned = YES;
    self.sticky = YES;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation]];
}

- (void)showPinned {
    if (!self.enabled) return;
    [self cancelTimer:&_doneTimer];
    self.pinned = YES;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation]];
}

// A task finished or failed: peek in for a few seconds, then leave unless the pointer is on the panel.
- (void)peek {
    if (!self.enabled) return;
    [self showOnScreen:[self screenForPoint:NSEvent.mouseLocation]];
    [self cancelTimer:&_doneTimer];
    __weak RelayNotchPanel *weakSelf = self;
    self.doneTimer = [NSTimer scheduledTimerWithTimeInterval:DoneVisibleSeconds repeats:NO block:^(NSTimer *timer) {
        RelayNotchPanel *strongSelf = weakSelf;
        if (!strongSelf || strongSelf.pinned) return;
        if (![strongSelf pointerIsNearPanel]) [strongSelf hideAnimated:YES];
    }];
}

#pragma mark - Pointer tracking

// The pointer and modifier keys are read 40 times a second. This works in every app and Space,
// needs no special permission, and also catches the very top pixel row that event monitors can miss.
- (void)installMonitors {
    if (self.pollTimer) return;
    __weak RelayNotchPanel *weakSelf = self;
    NSTimer *timer = [NSTimer timerWithTimeInterval:0.025 repeats:YES block:^(NSTimer *tick) {
        [weakSelf pointerMoved];
    }];
    timer.tolerance = 0.005;
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
    self.pollTimer = timer;
}

- (void)removeMonitors {
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
    CGFloat half = [self notchSizeForScreen:screen].width / 2 + TriggerMargin;
    return point.y >= NSMaxY(area) - TriggerDepth && fabs(point.x - NSMidX(area)) <= half;
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
            [strongSelf showOnScreen:[strongSelf screenForPoint:NSEvent.mouseLocation]];
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
        if (![strongSelf pointerIsNearPanel]) [strongSelf hideAnimated:YES];
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

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [webView reload];
}

@end
