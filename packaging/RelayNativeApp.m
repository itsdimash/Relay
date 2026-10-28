// Relay for macOS: a thin native shell around the local Relay engine.
// The engine (RelayServer) serves the dashboard on 127.0.0.1; this app starts it,
// shows the dashboard in a native window, and stops the engine when the app quits.
#import <Cocoa/Cocoa.h>
#include <signal.h>
#import <ServiceManagement/ServiceManagement.h>
#import <WebKit/WebKit.h>
#import "RelayNotchPanel.h"

// A fixed port keeps the dashboard's saved settings (team, models, drafts) between launches,
// because browser storage is tied to the address. If the port is busy, a free one is used.
static const int RelayPreferredPort = 48765;
static NSString *const RelaySkipMoveKey = @"RelaySkipMoveToApplications";

static NSString *const RelayNightWindowKey = @"RelayNightWindow";   // the theme the dashboard showed last, so the window opens in it
static NSString *const RelayThemeChoiceKey = @"RelayThemeChoice";   // "system", "light" or "night"

// Startup. Relay is a notch app first: it starts with the notch only, and the window opens when the person asks for it.
static NSString *const RelayOpenWindowAtLaunchKey = @"RelayOpenWindowAtLaunch"; // YES: also open the main window when Relay starts (default NO)
static NSString *const RelayHideDockKey = @"RelayHideDockWhenNotchOnly";        // YES: no Dock icon while only the notch is showing (default NO)
static NSString *const RelayLaunchedBeforeKey = @"RelayLaunchedBefore";         // the very first start opens the window once, so a new person sees the app

static NSColor *RelayColor(unsigned int rgb) {
    return [NSColor colorWithRed:((rgb >> 16) & 0xff) / 255.0
                           green:((rgb >> 8) & 0xff) / 255.0
                            blue:(rgb & 0xff) / 255.0
                           alpha:1.0];
}

// The window frame follows the dashboard's theme: the colour behind the page, the title bar and the scroll bars.
// With "system" the window must not be forced either way: the page reads the Mac's setting through the window's
// appearance, so a forced dark window would make System look dark forever.
static void RelayApplyWindowLook(NSWindow *window, BOOL night, BOOL followSystem) {
    window.backgroundColor = RelayColor(night ? 0x0d121b : 0xeceff4);
    window.appearance = followSystem ? nil : [NSAppearance appearanceNamed:night ? NSAppearanceNameDarkAqua : NSAppearanceNameAqua];
}

static BOOL RelayMacIsDark(void) {
    NSAppearanceName name = [NSApp.effectiveAppearance bestMatchFromAppearancesWithNames:@[ NSAppearanceNameAqua, NSAppearanceNameDarkAqua ]];
    return [name isEqualToString:NSAppearanceNameDarkAqua];
}

@interface RelayAppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler, RelayNotchPanelDelegate>
@property(nonatomic, strong) NSTask *server;
@property(nonatomic, strong) NSMutableString *outputBuffer;
@property(nonatomic, strong) NSMutableString *errorBuffer;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSURL *serverURL;
@property(nonatomic, strong) RelayNotchPanel *notch;
@property(nonatomic, strong) NSStatusItem *statusItem;   // only while the Dock icon is hidden: the way back in, and Quit
@property(nonatomic) BOOL opensWindowAtLaunch;           // decided in main(), before the app runs
@property(nonatomic) BOOL wantsWindow;                   // the window was asked for before the engine was ready
@property(nonatomic, copy) NSString *pendingHash;        // where the window should open, when it is built for a notch shortcut
@property(nonatomic) BOOL ready;
@property(nonatomic) BOOL triedPreferredPort;
@property(nonatomic) BOOL quitting;
@property(nonatomic) BOOL mayTerminate;
@end

@implementation RelayAppDelegate

- (instancetype)init {
    self = [super init];
    if (self) {
        _outputBuffer = [NSMutableString string];
        _errorBuffer = [NSMutableString string];
    }
    return self;
}

#pragma mark - Launch

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    [self buildMenu];
    self.wantsWindow = self.opensWindowAtLaunch;
    if ([self offerToMoveToApplications]) return;
    [self startServerOnPort:RelayPreferredPort];
}

- (void)buildMenu {
    NSMenu *mainMenu = [[NSMenu alloc] init];

    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Relay"];
    [appMenu addItemWithTitle:@"About Relay" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *startupItem = [appMenu addItemWithTitle:@"Startup" action:nil keyEquivalent:@""];
    NSMenu *startupMenu = [[NSMenu alloc] initWithTitle:@"Startup"];
    NSMenuItem *atLogin = [startupMenu addItemWithTitle:@"Open Relay at Login" action:@selector(toggleLaunchAtLogin:) keyEquivalent:@""];
    atLogin.target = self;
    NSMenuItem *withWindow = [startupMenu addItemWithTitle:@"Open the Window When Relay Starts" action:@selector(toggleOpenWindowAtLaunch:) keyEquivalent:@""];
    withWindow.target = self;
    NSMenuItem *hideDock = [startupMenu addItemWithTitle:@"Hide the Dock Icon While Only the Notch Is Showing" action:@selector(toggleHideDock:) keyEquivalent:@""];
    hideDock.target = self;
    startupItem.submenu = startupMenu;
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Hide Relay" action:@selector(hide:) keyEquivalent:@"h"];
    NSMenuItem *hideOthers = [appMenu addItemWithTitle:@"Hide Others" action:@selector(hideOtherApplications:) keyEquivalent:@"h"];
    hideOthers.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagOption;
    [appMenu addItemWithTitle:@"Show All" action:@selector(unhideAllApplications:) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Quit Relay" action:@selector(terminate:) keyEquivalent:@"q"];
    appItem.submenu = appMenu;

    // Without an Edit menu, copy and paste shortcuts do not reach the web view.
    NSMenuItem *editItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:editItem];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
    [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
    NSMenuItem *redo = [editMenu addItemWithTitle:@"Redo" action:@selector(redo:) keyEquivalent:@"z"];
    redo.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagShift;
    [editMenu addItem:[NSMenuItem separatorItem]];
    [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    editItem.submenu = editMenu;

    NSMenuItem *viewItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:viewItem];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    NSMenuItem *reload = [viewMenu addItemWithTitle:@"Reload" action:@selector(reloadDashboard:) keyEquivalent:@"r"];
    reload.target = self;
    NSMenuItem *fullScreen = [viewMenu addItemWithTitle:@"Enter Full Screen" action:@selector(toggleFullScreen:) keyEquivalent:@"f"];
    fullScreen.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagControl;
    [viewMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *showNotch = [viewMenu addItemWithTitle:@"Show or Hide Notch Panel (double-tap right ⌘)" action:@selector(showNotchPanel:) keyEquivalent:@""];
    showNotch.target = self;
    NSMenuItem *toggleNotch = [viewMenu addItemWithTitle:@"Open Notch Panel from Screen Top" action:@selector(toggleNotchPanel:) keyEquivalent:@""];
    toggleNotch.target = self;
    viewItem.submenu = viewMenu;

    NSMenuItem *windowItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:windowItem];
    NSMenu *windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
    [windowMenu addItemWithTitle:@"Minimize" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
    [windowMenu addItemWithTitle:@"Zoom" action:@selector(performZoom:) keyEquivalent:@""];
    [windowMenu addItemWithTitle:@"Close" action:@selector(performClose:) keyEquivalent:@"w"];
    windowItem.submenu = windowMenu;
    NSApp.windowsMenu = windowMenu;

    NSApp.mainMenu = mainMenu;
}

- (void)reloadDashboard:(id)sender {
    [self.webView reload];
}

- (void)showNotchPanel:(id)sender {
    [self.notch toggle];
}

- (void)toggleNotchPanel:(id)sender {
    self.notch.enabled = !self.notch.enabled;
}

- (BOOL)validateMenuItem:(NSMenuItem *)item {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    if (item.action == @selector(toggleLaunchAtLogin:)) {
        item.state = SMAppService.mainAppService.status == SMAppServiceStatusEnabled ? NSControlStateValueOn : NSControlStateValueOff;
        return YES;
    }
    if (item.action == @selector(toggleOpenWindowAtLaunch:)) {
        item.state = [defaults boolForKey:RelayOpenWindowAtLaunchKey] ? NSControlStateValueOn : NSControlStateValueOff;
        return YES;
    }
    if (item.action == @selector(toggleHideDock:)) {
        item.state = [defaults boolForKey:RelayHideDockKey] ? NSControlStateValueOn : NSControlStateValueOff;
        return YES;
    }
    if (item.action == @selector(toggleNotchPanel:)) {
        item.state = self.notch.enabled ? NSControlStateValueOn : NSControlStateValueOff;
        return self.notch != nil;
    }
    if (item.action == @selector(showNotchPanel:)) return self.notch != nil;
    return YES;
}

#pragma mark - Notch panel

- (void)notchPanelRequestsOpenRelay {
    [self showMainWindow];
}

#pragma mark - Startup settings

// The three choices of the Startup menu in the Relay menu. The dashboard's Startup button shows and changes the same ones.
- (NSDictionary<NSString *, NSNumber *> *)startupSettings {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    return @{ @"login": @(SMAppService.mainAppService.status == SMAppServiceStatusEnabled),
              @"window": @([defaults boolForKey:RelayOpenWindowAtLaunchKey]),
              @"hideDock": @([defaults boolForKey:RelayHideDockKey]) };
}

- (void)pushStartupSettings {
    [self.webView callAsyncJavaScript:@"if (window.relayStartup) window.relayStartup(settings);"
                            arguments:@{ @"settings": [self startupSettings] }
                              inFrame:nil
                       inContentWorld:WKContentWorld.pageWorld
                    completionHandler:nil];
}

- (void)setStartupSetting:(NSString *)name enabled:(BOOL)enabled {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    if ([name isEqualToString:@"login"]) {
        [self setLaunchAtLogin:enabled];
    } else if ([name isEqualToString:@"window"]) {
        [defaults setBool:enabled forKey:RelayOpenWindowAtLaunchKey];
    } else if ([name isEqualToString:@"hideDock"]) {
        [defaults setBool:enabled forKey:RelayHideDockKey];
        [self applyActivationPolicy];
    }
}

- (void)toggleOpenWindowAtLaunch:(id)sender {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    [defaults setBool:![defaults boolForKey:RelayOpenWindowAtLaunchKey] forKey:RelayOpenWindowAtLaunchKey];
}

- (void)toggleHideDock:(id)sender {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    [defaults setBool:![defaults boolForKey:RelayHideDockKey] forKey:RelayHideDockKey];
    [self applyActivationPolicy];
}

// "Open Relay at Login" is a normal macOS login item. It is listed in System Settings › General › Login Items.
- (void)toggleLaunchAtLogin:(id)sender {
    [self setLaunchAtLogin:SMAppService.mainAppService.status != SMAppServiceStatusEnabled];
}

- (void)setLaunchAtLogin:(BOOL)on {
    SMAppService *service = SMAppService.mainAppService;
    BOOL wasOn = service.status == SMAppServiceStatusEnabled;
    if (on == wasOn) return;
    NSError *error = nil;
    BOOL done = wasOn ? [service unregisterAndReturnError:&error] : [service registerAndReturnError:&error];
    if (!done) {
        [NSApp activateIgnoringOtherApps:YES];
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = wasOn ? @"Relay could not be removed from your login items." : @"Relay could not be added to your login items.";
        alert.informativeText = [NSString stringWithFormat:@"You can change it yourself in System Settings › General › Login Items. %@", error.localizedDescription ?: @""];
        [alert runModal];
        return;
    }
    if (!wasOn && service.status == SMAppServiceStatusRequiresApproval) {
        [NSApp activateIgnoringOtherApps:YES];
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Allow Relay in Login Items.";
        alert.informativeText = @"macOS needs your approval first. Turn Relay on in System Settings › General › Login Items.";
        [alert addButtonWithTitle:@"Open Login Items"];
        [alert addButtonWithTitle:@"Not Now"];
        if ([alert runModal] == NSAlertFirstButtonReturn) [SMAppService openSystemSettingsLoginItems];
    }
}

#pragma mark - Dock icon and menu bar item

// The Dock icon stays while the window is open. With the notch only, it can go (a setting), and a small menu bar item
// takes its place: the way back to the window, and Quit. Without either, Relay would have no way to be opened or quit.
- (void)applyActivationPolicy {
    BOOL windowShown = self.window && (self.window.visible || self.window.miniaturized);
    BOOL hideDock = !windowShown && self.notch.enabled && [NSUserDefaults.standardUserDefaults boolForKey:RelayHideDockKey];
    NSApplicationActivationPolicy wanted = hideDock ? NSApplicationActivationPolicyAccessory : NSApplicationActivationPolicyRegular;
    if (NSApp.activationPolicy != wanted) [NSApp setActivationPolicy:wanted];
    [self showStatusItem:hideDock];
}

- (void)showStatusItem:(BOOL)show {
    if (!show) {
        if (self.statusItem) [NSStatusBar.systemStatusBar removeStatusItem:self.statusItem];
        self.statusItem = nil;
        return;
    }
    if (self.statusItem) return;
    NSStatusItem *item = [NSStatusBar.systemStatusBar statusItemWithLength:NSSquareStatusItemLength];
    NSURL *iconURL = [NSBundle.mainBundle URLForResource:@"relay-status" withExtension:@"png"];
    NSImage *icon = iconURL ? [[NSImage alloc] initWithContentsOfURL:iconURL] : nil;
    if (icon) {
        icon.size = NSMakeSize(18, 18);
        item.button.image = icon;
    } else {
        item.button.title = @"Relay";
    }
    NSMenu *menu = [[NSMenu alloc] init];
    NSMenuItem *open = [menu addItemWithTitle:@"Open Relay" action:@selector(openFromStatusItem:) keyEquivalent:@""];
    open.target = self;
    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *quit = [menu addItemWithTitle:@"Quit Relay" action:@selector(quitFromStatusItem:) keyEquivalent:@""];
    quit.target = self;
    item.menu = menu;
    self.statusItem = item;
}

- (void)openFromStatusItem:(id)sender {
    [self showMainWindow];
}

- (void)quitFromStatusItem:(id)sender {
    [NSApp terminate:nil];
}

- (void)mainWindowWillClose:(NSNotification *)notification {
    // The window is not hidden yet while this runs, so look again on the next turn.
    dispatch_async(dispatch_get_main_queue(), ^{ [self applyActivationPolicy]; });
}

- (void)notchPanelRequestsOpenRelayAt:(NSDictionary *)destination {
    NSURLComponents *components = [[NSURLComponents alloc] init];
    NSMutableArray *items = [NSMutableArray array];
    for (NSString *key in @[@"run", @"tab", @"step"]) {
        [items addObject:[NSURLQueryItem queryItemWithName:key value:destination[key]]];
    }
    components.queryItems = items;
    NSData *json = [NSJSONSerialization dataWithJSONObject:@[components.percentEncodedQuery ?: @""] options:0 error:nil];
    NSString *argument = [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
    if (!self.webView) self.pendingHash = components.percentEncodedQuery ?: @"";
    if (argument && self.webView) [self.webView evaluateJavaScript:[NSString stringWithFormat:@"(function(h){if(window.location.hash.slice(1)===h){window.dispatchEvent(new Event('hashchange'));}else{window.location.hash=h;}})((%@)[0]);", argument] completionHandler:nil];
    [self showMainWindow];
}

// The window is built the first time it is asked for, so a Relay that only shows the notch does not carry a web view.
- (void)showMainWindow {
    if (!self.serverURL) { self.wantsWindow = YES; return; } // the engine is still starting: the window opens when it is ready
    [self buildWindowIfNeeded];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    if (self.window.miniaturized) [self.window deminiaturize:nil];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [self showStatusItem:NO];
}

#pragma mark - Move to Applications

// Opened from Downloads, a downloaded app gets deleted with that folder. Offer to install it properly.
- (BOOL)offerToMoveToApplications {
    NSString *bundlePath = NSBundle.mainBundle.bundlePath;
    NSString *userApplications = [NSHomeDirectory() stringByAppendingPathComponent:@"Applications/"];
    if ([bundlePath hasPrefix:@"/Applications/"] || [bundlePath hasPrefix:userApplications]) return NO;
    if ([NSUserDefaults.standardUserDefaults boolForKey:RelaySkipMoveKey]) return NO;

    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular]; // a Dock-less app cannot show this question properly
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *ask = [[NSAlert alloc] init];
    ask.messageText = @"Move Relay to your Applications folder?";
    ask.informativeText = @"Relay is running from a temporary location, such as Downloads. Moving it to Applications keeps it with your other apps and stops it from being deleted by accident.";
    [ask addButtonWithTitle:@"Move to Applications"];
    [ask addButtonWithTitle:@"Not Now"];
    ask.showsSuppressionButton = YES;
    ask.suppressionButton.title = @"Don’t ask again";
    NSModalResponse answer = [ask runModal];
    if (ask.suppressionButton.state == NSControlStateValueOn) {
        [NSUserDefaults.standardUserDefaults setBool:YES forKey:RelaySkipMoveKey];
    }
    if (answer != NSAlertFirstButtonReturn) return NO;

    NSFileManager *files = NSFileManager.defaultManager;
    NSURL *source = NSBundle.mainBundle.bundleURL;
    NSURL *destination = [NSURL fileURLWithPath:@"/Applications/Relay.app"];
    NSError *error = nil;

    if ([files fileExistsAtPath:destination.path]) {
        NSAlert *replace = [[NSAlert alloc] init];
        replace.messageText = @"Relay is already in Applications.";
        replace.informativeText = @"Replace it with this version? The old copy goes to the Trash.";
        [replace addButtonWithTitle:@"Replace"];
        [replace addButtonWithTitle:@"Cancel"];
        if ([replace runModal] != NSAlertFirstButtonReturn) return NO;
        if (![files trashItemAtURL:destination resultingItemURL:nil error:&error]) {
            [self showMoveFailure:error];
            return NO;
        }
    }
    if (![files copyItemAtURL:source toURL:destination error:&error]) {
        [self showMoveFailure:error];
        return NO;
    }

    // The person already approved this app in System Settings, so the copy does not need to ask again.
    NSTask *clear = [[NSTask alloc] init];
    clear.executableURL = [NSURL fileURLWithPath:@"/usr/bin/xattr"];
    clear.arguments = @[@"-dr", @"com.apple.quarantine", destination.path];
    if ([clear launchAndReturnError:nil]) [clear waitUntilExit];

    // Remove the original when it is a normal file, not a read-only translocated or disk-image copy.
    if ([bundlePath rangeOfString:@"/AppTranslocation/"].location == NSNotFound &&
        ![bundlePath hasPrefix:@"/Volumes/"]) {
        [files trashItemAtURL:source resultingItemURL:nil error:nil];
    }

    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.createsNewApplicationInstance = YES;
    __weak RelayAppDelegate *weakSelf = self;
    [NSWorkspace.sharedWorkspace openApplicationAtURL:destination
                                        configuration:configuration
                                    completionHandler:^(NSRunningApplication *app, NSError *openError) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (openError) {
                [weakSelf showMoveFailure:openError];
                [weakSelf startServerOnPort:RelayPreferredPort];
                return;
            }
            weakSelf.mayTerminate = YES;
            [NSApp terminate:nil];
        });
    }];
    return YES;
}

- (void)showMoveFailure:(NSError *)error {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Relay could not be moved.";
    alert.informativeText = [NSString stringWithFormat:@"You can drag Relay into the Applications folder yourself. %@", error.localizedDescription ?: @""];
    [alert runModal];
}

#pragma mark - Engine

- (void)startServerOnPort:(int)port {
    NSURL *resourceURL = NSBundle.mainBundle.resourceURL;
    NSURL *executable = [resourceURL URLByAppendingPathComponent:@"RelayServer"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:executable.path]) {
        [self fatal:@"Relay's engine is missing."];
        return;
    }
    self.triedPreferredPort = (port == RelayPreferredPort);
    [self.outputBuffer setString:@""];
    [self.errorBuffer setString:@""];

    NSTask *process = [[NSTask alloc] init];
    NSPipe *output = [NSPipe pipe], *errors = [NSPipe pipe];
    process.executableURL = executable;
    process.arguments = @[@"--port", [NSString stringWithFormat:@"%d", port]];
    process.standardOutput = output;
    process.standardError = errors;
    process.currentDirectoryURL = resourceURL;
    // Tell the engine which app it belongs to so it can offer in-app updates.
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    NSString *version = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"];
    if (version.length) environment[@"RELAY_APP_VERSION"] = version;
    environment[@"RELAY_APP_PATH"] = NSBundle.mainBundle.bundlePath;
    environment[@"RELAY_APP_PID"] = [NSString stringWithFormat:@"%d", NSProcessInfo.processInfo.processIdentifier];
    process.environment = environment;
    __weak RelayAppDelegate *weakSelf = self;
    output.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (!data.length) { handle.readabilityHandler = nil; return; }
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        if (text) dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf consumeOutput:text]; });
    };
    errors.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (!data.length) { handle.readabilityHandler = nil; return; }
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        if (text) dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf.errorBuffer appendString:text]; });
    };
    process.terminationHandler = ^(NSTask *task) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf serverStopped:task]; });
    };
    NSError *error = nil;
    if ([process launchAndReturnError:&error]) {
        self.server = process;
    } else {
        [self fatal:[NSString stringWithFormat:@"Relay could not start: %@", error.localizedDescription]];
    }
}

- (void)consumeOutput:(NSString *)text {
    [self.outputBuffer appendString:text];
    NSRange newline;
    while ((newline = [self.outputBuffer rangeOfString:@"\n"]).location != NSNotFound) {
        NSString *line = [self.outputBuffer substringToIndex:newline.location];
        [self.outputBuffer deleteCharactersInRange:NSMakeRange(0, NSMaxRange(newline))];
        NSString *prefix = @"Relay is ready at ";
        if ([line hasPrefix:prefix]) {
            NSURL *url = [NSURL URLWithString:[line substringFromIndex:prefix.length]];
            if (url && !self.ready) {
                self.ready = YES;
                [self engineReadyAtURL:url];
            }
        }
    }
}

- (void)serverStopped:(NSTask *)task {
    if (task != self.server) return;
    self.server = nil;
    if (self.quitting) { self.mayTerminate = YES; [NSApp terminate:nil]; return; }
    // Exit status 75: the engine finished downloading an update and asked the app to quit so it can be replaced.
    if (task.terminationStatus == 75) { self.mayTerminate = YES; [NSApp terminate:nil]; return; }
    NSString *details = [self.errorBuffer stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    // Preferred port taken by another program: try again on any free port.
    if (!self.ready && self.triedPreferredPort && [details containsString:@"Could not start Relay"]) {
        [self startServerOnPort:0];
        return;
    }
    [self fatal:details.length ? details : [NSString stringWithFormat:@"Relay's local engine stopped unexpectedly (status %d).", task.terminationStatus]];
}

#pragma mark - Window

// The engine is up. The notch always starts; the main window only when it was asked for (a setting, the first start ever,
// a notch shortcut, or the notch being turned off, which would leave nothing to see).
- (void)engineReadyAtURL:(NSURL *)url {
    self.serverURL = url;
    // Marked here, not at launch: when Relay moves itself to Applications, the copy that opens next is still the first start.
    [NSUserDefaults.standardUserDefaults setBool:YES forKey:RelayLaunchedBeforeKey];
    if (!self.notch) {
        NSURL *notchURL = [NSURL URLWithString:@"notch" relativeToURL:url].absoluteURL;
        self.notch = [[RelayNotchPanel alloc] initWithPageURL:notchURL];
        self.notch.delegate = self;
    }
    if (self.wantsWindow || !self.notch.enabled) [self showMainWindow];
    [self applyActivationPolicy];
}

- (void)buildWindowIfNeeded {
    if (self.window || !self.serverURL) return;
    NSURL *url = self.serverURL;

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    // The dashboard tells the window which theme it shows (Appearance menu in its header).
    [configuration.userContentController addScriptMessageHandler:self name:@"relayWindow"];
    WKWebView *webView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
    webView.navigationDelegate = self;
    webView.UIDelegate = self;
    webView.allowsBackForwardNavigationGestures = NO;
    webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView = webView;

    NSRect frame = NSMakeRect(0, 0, 1280, 820);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:frame
                                                  styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
                                                    backing:NSBackingStoreBuffered
                                                      defer:NO];
    window.title = @"Relay";
    // The notch panel keeps the app alive after this window is closed, so the window must survive closing.
    window.releasedWhenClosed = NO;
    window.minSize = NSMakeSize(900, 620);
    window.titlebarAppearsTransparent = YES;
    NSString *savedChoice = [NSUserDefaults.standardUserDefaults stringForKey:RelayThemeChoiceKey];
    BOOL followSystem = [savedChoice isEqualToString:@"system"];
    BOOL savedNight = followSystem ? RelayMacIsDark() : [NSUserDefaults.standardUserDefaults boolForKey:RelayNightWindowKey];
    RelayApplyWindowLook(window, savedNight, followSystem);
    webView.frame = ((NSView *)window.contentView).bounds;
    [window.contentView addSubview:webView];
    [window center];
    [window setFrameAutosaveName:@"RelayMainWindow"];
    self.window = window;
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(mainWindowWillClose:) name:NSWindowWillCloseNotification object:window];

    NSURL *initial = url;
    if (self.pendingHash.length) {
        NSURLComponents *parts = [NSURLComponents componentsWithURL:url resolvingAgainstBaseURL:NO];
        parts.percentEncodedFragment = self.pendingHash;
        initial = parts.URL ?: url;
    }
    self.pendingHash = nil;
    [webView loadRequest:[NSURLRequest requestWithURL:initial]];
}

#pragma mark - WKScriptMessageHandler

- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    if (![message.name isEqualToString:@"relayWindow"] || ![message.body isKindOfClass:NSDictionary.class]) return;
    if (![self isLocalDashboardURL:message.frameInfo.request.URL]) return; // only Relay's own page may ask
    NSDictionary *body = message.body;
    if ([body[@"type"] isEqual:@"theme"] && self.window) {
        BOOL night = [body[@"night"] boolValue];
        NSString *choice = [body[@"choice"] isKindOfClass:NSString.class] ? body[@"choice"] : @"light";
        BOOL followSystem = [choice isEqualToString:@"system"];
        [NSUserDefaults.standardUserDefaults setBool:night forKey:RelayNightWindowKey];
        [NSUserDefaults.standardUserDefaults setObject:(followSystem ? @"system" : (night ? @"night" : @"light")) forKey:RelayThemeChoiceKey];
        RelayApplyWindowLook(self.window, night, followSystem);
    } else if ([body[@"type"] isEqual:@"startup"]) {
        // The dashboard's Startup menu. With a name it changes one choice; without, it only asks for the current ones.
        NSString *name = [body[@"name"] isKindOfClass:NSString.class] ? body[@"name"] : @"";
        if ([@[ @"login", @"window", @"hideDock" ] containsObject:name] && [body[@"on"] isKindOfClass:NSNumber.class]) {
            [self setStartupSetting:name enabled:[body[@"on"] boolValue]];
        }
        [self pushStartupSettings];
    }
}

- (BOOL)isLocalDashboardURL:(NSURL *)url {
    if (!url || !self.serverURL) return NO;
    if ([url.scheme isEqualToString:@"about"] || [url.scheme isEqualToString:@"blob"] || [url.scheme isEqualToString:@"data"]) return YES;
    return [url.host isEqualToString:self.serverURL.host] && [url.port isEqualToNumber:self.serverURL.port];
}

#pragma mark - WKNavigationDelegate

- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = action.request.URL;
    if (![self isLocalDashboardURL:url]) {
        // Anything that is not Relay's own dashboard opens in the default browser.
        if (url && ([url.scheme isEqualToString:@"http"] || [url.scheme isEqualToString:@"https"] || [url.scheme isEqualToString:@"mailto"])) {
            [NSWorkspace.sharedWorkspace openURL:url];
        }
        decisionHandler(WKNavigationActionPolicyCancel);
        return;
    }
    if (action.shouldPerformDownload) {
        decisionHandler(WKNavigationActionPolicyDownload);
        return;
    }
    decisionHandler(WKNavigationActionPolicyAllow);
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    NSHTTPURLResponse *http = [response.response isKindOfClass:NSHTTPURLResponse.class] ? (NSHTTPURLResponse *)response.response : nil;
    NSString *disposition = http.allHeaderFields[@"Content-Disposition"];
    BOOL attachment = [disposition isKindOfClass:NSString.class] && [disposition.lowercaseString hasPrefix:@"attachment"];
    if (attachment || !response.canShowMIMEType) {
        decisionHandler(WKNavigationResponsePolicyDownload);
        return;
    }
    decisionHandler(WKNavigationResponsePolicyAllow);
}

- (void)webView:(WKWebView *)webView navigationAction:(WKNavigationAction *)action didBecomeDownload:(WKDownload *)download {
    download.delegate = self;
}

- (void)webView:(WKWebView *)webView navigationResponse:(WKNavigationResponse *)response didBecomeDownload:(WKDownload *)download {
    download.delegate = self;
}

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    [webView reload];
}

#pragma mark - WKDownloadDelegate

- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response suggestedFilename:(NSString *)suggestedFilename completionHandler:(void (^)(NSURL *destination))completionHandler {
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.nameFieldStringValue = suggestedFilename ?: @"relay-changes.patch";
    panel.canCreateDirectories = YES;
    void (^finish)(NSModalResponse) = ^(NSModalResponse result) {
        if (result != NSModalResponseOK || !panel.URL) { completionHandler(nil); return; }
        // The panel already asked about replacing; a download needs a free destination.
        [NSFileManager.defaultManager removeItemAtURL:panel.URL error:nil];
        completionHandler(panel.URL);
    };
    if (self.window) [panel beginSheetModalForWindow:self.window completionHandler:finish];
    else finish([panel runModal]);
}

- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"The download did not finish.";
    alert.informativeText = error.localizedDescription ?: @"";
    [alert runModal];
}

#pragma mark - WKUIDelegate

// Links that ask for a new window (for example saved screenshots) open in the default browser.
- (WKWebView *)webView:(WKWebView *)webView createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)windowFeatures {
    NSURL *url = action.request.URL;
    if (url) [NSWorkspace.sharedWorkspace openURL:url];
    return nil;
}

// "Attach images" needs a native file chooser.
- (void)webView:(WKWebView *)webView runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *URLs))completionHandler {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection;
    panel.canChooseDirectories = parameters.allowsDirectories;
    panel.canChooseFiles = YES;
    void (^finish)(NSModalResponse) = ^(NSModalResponse result) {
        completionHandler(result == NSModalResponseOK ? panel.URLs : nil);
    };
    if (self.window) [panel beginSheetModalForWindow:self.window completionHandler:finish];
    else finish([panel runModal]);
}

- (void)webView:(WKWebView *)webView runJavaScriptAlertPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(void))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = message;
    [alert runModal];
    completionHandler();
}

- (void)webView:(WKWebView *)webView runJavaScriptConfirmPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(BOOL result))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = message;
    [alert addButtonWithTitle:@"OK"];
    [alert addButtonWithTitle:@"Cancel"];
    completionHandler([alert runModal] == NSAlertFirstButtonReturn);
}

#pragma mark - App lifecycle

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!self.window.visible) [self showMainWindow];
    return YES;
}

// With the notch panel on, Relay keeps running after its window closes so the panel can still show the task.
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return !self.notch.enabled; }

- (void)fatal:(NSString *)message {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Relay could not start";
    alert.informativeText = message;
    alert.alertStyle = NSAlertStyleCritical;
    [alert runModal];
    self.mayTerminate = YES;
    [NSApp terminate:nil];
}

// Quit waits for the engine to save any running task before the app exits.
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (self.mayTerminate || !self.server.running) return NSTerminateNow;
    if (!self.quitting) {
        self.quitting = YES;
        NSTask *engine = self.server;
        [engine terminate];
        // The engine saves a running task before it exits, which can take a while. If it is still there after
        // 10 seconds, stop waiting: Quit must always finish. The data folder is released when the process ends.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if (engine.running) kill(engine.processIdentifier, SIGKILL);
        });
    }
    return NSTerminateCancel;
}

@end

static RelayAppDelegate *RelayApplicationDelegate;

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        RelayApplicationDelegate = [[RelayAppDelegate alloc] init];
        app.delegate = RelayApplicationDelegate;

        NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
        [defaults registerDefaults:@{RelayNotchEnabledKey: @YES, RelayOpenWindowAtLaunchKey: @NO, RelayHideDockKey: @NO}];
        // Someone who has used Relay before has a saved theme; only a brand new install has neither it nor the launched-before mark.
        BOOL firstStart = ![defaults objectForKey:RelayLaunchedBeforeKey] && ![defaults objectForKey:RelayThemeChoiceKey];
        BOOL opensWindow = firstStart || [defaults boolForKey:RelayOpenWindowAtLaunchKey] || ![defaults boolForKey:RelayNotchEnabledKey];
        RelayApplicationDelegate.opensWindowAtLaunch = opensWindow;
        BOOL hidesDock = !opensWindow && [defaults boolForKey:RelayHideDockKey];
        [app setActivationPolicy:hidesDock ? NSApplicationActivationPolicyAccessory : NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
