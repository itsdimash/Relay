// Relay for macOS: a thin native shell around the local Relay engine.
// The engine (RelayServer) serves the dashboard on 127.0.0.1; this app starts it,
// shows the dashboard in a native window, and stops the engine when the app quits.
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import "RelayNotchPanel.h"

// A fixed port keeps the dashboard's saved settings (team, models, drafts) between launches,
// because browser storage is tied to the address. If the port is busy, a free one is used.
static const int RelayPreferredPort = 48765;
static NSString *const RelaySkipMoveKey = @"RelaySkipMoveToApplications";

static NSColor *RelayColor(unsigned int rgb) {
    return [NSColor colorWithRed:((rgb >> 16) & 0xff) / 255.0
                           green:((rgb >> 8) & 0xff) / 255.0
                            blue:(rgb & 0xff) / 255.0
                           alpha:1.0];
}

@interface RelayAppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, RelayNotchPanelDelegate>
@property(nonatomic, strong) NSTask *server;
@property(nonatomic, strong) NSMutableString *outputBuffer;
@property(nonatomic, strong) NSMutableString *errorBuffer;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSURL *serverURL;
@property(nonatomic, strong) RelayNotchPanel *notch;
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

- (void)showMainWindow {
    if (self.window.miniaturized) [self.window deminiaturize:nil];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

#pragma mark - Move to Applications

// Opened from Downloads, a downloaded app gets deleted with that folder. Offer to install it properly.
- (BOOL)offerToMoveToApplications {
    NSString *bundlePath = NSBundle.mainBundle.bundlePath;
    NSString *userApplications = [NSHomeDirectory() stringByAppendingPathComponent:@"Applications/"];
    if ([bundlePath hasPrefix:@"/Applications/"] || [bundlePath hasPrefix:userApplications]) return NO;
    if ([NSUserDefaults.standardUserDefaults boolForKey:RelaySkipMoveKey]) return NO;

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
                [self openWindowForURL:url];
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

- (void)openWindowForURL:(NSURL *)url {
    self.serverURL = url;

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
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
    window.backgroundColor = RelayColor(0xeceff4);
    window.titlebarAppearsTransparent = YES;
    window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
    webView.frame = ((NSView *)window.contentView).bounds;
    [window.contentView addSubview:webView];
    [window center];
    [window setFrameAutosaveName:@"RelayMainWindow"];
    [window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    self.window = window;

    [webView loadRequest:[NSURLRequest requestWithURL:url]];

    if (!self.notch) {
        NSURL *notchURL = [NSURL URLWithString:@"notch" relativeToURL:url].absoluteURL;
        self.notch = [[RelayNotchPanel alloc] initWithPageURL:notchURL];
        self.notch.delegate = self;
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
    if (!self.quitting) { self.quitting = YES; [self.server terminate]; }
    return NSTerminateCancel;
}

@end

static RelayAppDelegate *RelayApplicationDelegate;

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        RelayApplicationDelegate = [[RelayAppDelegate alloc] init];
        app.delegate = RelayApplicationDelegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
