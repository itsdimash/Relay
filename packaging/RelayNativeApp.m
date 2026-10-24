#import <Cocoa/Cocoa.h>

static NSColor *RelayColor(unsigned int rgb) {
    return [NSColor colorWithRed:((rgb >> 16) & 0xff) / 255.0
                           green:((rgb >> 8) & 0xff) / 255.0
                            blue:(rgb & 0xff) / 255.0
                           alpha:1.0];
}

static NSTextField *RelayLabel(NSString *text, CGFloat size, NSFontWeight weight, NSColor *color) {
    NSTextField *label = [NSTextField labelWithString:text ?: @""];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    label.textColor = color;
    label.lineBreakMode = NSLineBreakByTruncatingTail;
    return label;
}

static NSButton *RelayButton(NSString *title, id target, SEL action, BOOL primary) {
    NSButton *button = [NSButton buttonWithTitle:title target:target action:action];
    button.font = [NSFont systemFontOfSize:13 weight:NSFontWeightMedium];
    button.bezelStyle = NSBezelStyleRounded;
    button.controlSize = NSControlSizeLarge;
    button.translatesAutoresizingMaskIntoConstraints = NO;
    [button.heightAnchor constraintEqualToConstant:34].active = YES;
    if (primary) {
        button.bordered = NO;
        button.wantsLayer = YES;
        button.layer.backgroundColor = RelayColor(0x225b4d).CGColor;
        button.layer.cornerRadius = 7;
        button.contentTintColor = NSColor.whiteColor;
    }
    return button;
}

@interface RelaySurfaceView : NSView
@property(nonatomic, strong) NSColor *fillColor;
@property(nonatomic, strong) NSColor *edgeColor;
@property(nonatomic) CGFloat radius;
@end

@implementation RelaySurfaceView
- (instancetype)init {
    self = [super init];
    if (self) {
        self.wantsLayer = YES;
        _fillColor = NSColor.whiteColor;
        _edgeColor = RelayColor(0xe7ebe8);
        _radius = 12;
    }
    return self;
}
- (void)layout {
    [super layout];
    self.layer.backgroundColor = self.fillColor.CGColor;
    self.layer.borderColor = self.edgeColor.CGColor;
    self.layer.borderWidth = self.edgeColor ? 1 : 0;
    self.layer.cornerRadius = self.radius;
}
@end

@interface RelayAPIClient : NSObject
@property(nonatomic, strong) NSURL *baseURL;
@property(nonatomic, copy) NSString *token;
- (void)get:(NSString *)path completion:(void (^)(NSDictionary *, NSError *))completion;
- (void)post:(NSString *)path body:(NSDictionary *)body completion:(void (^)(NSDictionary *, NSError *))completion;
@end

@implementation RelayAPIClient
- (void)request:(NSString *)path body:(NSDictionary *)body completion:(void (^)(NSDictionary *, NSError *))completion {
    NSURL *url = [NSURL URLWithString:path relativeToURL:self.baseURL];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    request.timeoutInterval = 45;
    if (body) {
        request.HTTPMethod = @"POST";
        request.HTTPBody = [NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
        [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
        [request setValue:self.token ?: @"" forHTTPHeaderField:@"X-Relay-Token"];
    }
    [[[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSDictionary *json = nil;
        if (data.length) json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSInteger status = [(NSHTTPURLResponse *)response statusCode];
        if (!error && (status < 200 || status >= 300)) {
            NSString *message = [json[@"error"] isKindOfClass:NSString.class] ? json[@"error"] : @"Relay could not complete that request.";
            error = [NSError errorWithDomain:@"Relay" code:status userInfo:@{NSLocalizedDescriptionKey: message}];
        }
        dispatch_async(dispatch_get_main_queue(), ^{ completion(json ?: @{}, error); });
    }] resume];
}
- (void)get:(NSString *)path completion:(void (^)(NSDictionary *, NSError *))completion {
    [self request:path body:nil completion:completion];
}
- (void)post:(NSString *)path body:(NSDictionary *)body completion:(void (^)(NSDictionary *, NSError *))completion {
    [self request:path body:body completion:completion];
}
@end

@interface RelayHistoryCell : NSTableCellView
@property(nonatomic, strong) NSTextField *subtitle;
@end

@implementation RelayHistoryCell
- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        NSTextField *title = RelayLabel(@"", 13, NSFontWeightMedium, RelayColor(0x1b2420));
        NSTextField *subtitle = RelayLabel(@"", 11, NSFontWeightRegular, RelayColor(0x65706b));
        title.translatesAutoresizingMaskIntoConstraints = NO;
        subtitle.translatesAutoresizingMaskIntoConstraints = NO;
        [self addSubview:title];
        [self addSubview:subtitle];
        self.textField = title;
        self.subtitle = subtitle;
        [NSLayoutConstraint activateConstraints:@[
            [title.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:10],
            [title.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-8],
            [title.topAnchor constraintEqualToAnchor:self.topAnchor constant:7],
            [subtitle.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
            [subtitle.trailingAnchor constraintEqualToAnchor:title.trailingAnchor],
            [subtitle.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:3]
        ]];
    }
    return self;
}
@end

@interface RelayWorkspaceController : NSViewController <NSTableViewDataSource, NSTableViewDelegate, NSTextViewDelegate>
@property(nonatomic, strong) RelayAPIClient *api;
@property(nonatomic, strong) NSArray<NSDictionary *> *runs;
@property(nonatomic, strong) NSArray<NSDictionary *> *projects;
@property(nonatomic, strong) NSDictionary *defaultTeam;
@property(nonatomic, strong) NSDictionary *connections;
@property(nonatomic, strong) NSTableView *historyTable;
@property(nonatomic, strong) NSTextField *localStatus;
@property(nonatomic, strong) RelaySurfaceView *sheet;
@property(nonatomic, strong) NSView *screenHost;
@property(nonatomic, strong) NSView *composer;
@property(nonatomic, strong) NSView *detail;
@property(nonatomic, strong) NSPopUpButton *projectPopup;
@property(nonatomic, strong) NSSegmentedControl *modeControl;
@property(nonatomic, strong) NSTextView *taskEditor;
@property(nonatomic, strong) NSPopUpButton *roundsPopup;
@property(nonatomic, strong) NSPopUpButton *minutesPopup;
@property(nonatomic, strong) NSMutableDictionary<NSString *, NSPopUpButton *> *rolePopups;
@property(nonatomic, strong) NSTextField *connectionSummary;
@property(nonatomic, strong) NSButton *startButton;
@property(nonatomic, strong) NSTextField *composerError;
@property(nonatomic, copy) NSString *selectedRunID;
@property(nonatomic, strong) NSTextField *detailTitle;
@property(nonatomic, strong) NSTextField *detailSubtitle;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSTextView *transcript;
@property(nonatomic, strong) NSStackView *decisionStack;
@property(nonatomic, strong) NSButton *pauseButton;
@property(nonatomic, strong) NSButton *stopButton;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, strong) NSMutableDictionary<NSString *, NSTextField *> *answerFields;
@end

@implementation RelayWorkspaceController

- (instancetype)initWithAPI:(RelayAPIClient *)api {
    self = [super init];
    if (self) {
        _api = api;
        _runs = @[];
        _projects = @[];
        _rolePopups = [NSMutableDictionary dictionary];
        _answerFields = [NSMutableDictionary dictionary];
    }
    return self;
}

- (void)loadView {
    RelaySurfaceView *root = [[RelaySurfaceView alloc] init];
    root.fillColor = RelayColor(0xf1f5f3);
    root.edgeColor = nil;
    root.radius = 0;
    self.view = root;
    [self buildShell];
    [self showComposer:nil];
    [self initialLoad];
}

- (void)buildShell {
    NSView *sidebar = [[NSView alloc] init];
    sidebar.translatesAutoresizingMaskIntoConstraints = NO;
    sidebar.wantsLayer = YES;
    sidebar.layer.backgroundColor = RelayColor(0xf1f5f3).CGColor;
    [self.view addSubview:sidebar];

    NSImageView *mark = [[NSImageView alloc] init];
    mark.image = [NSImage imageNamed:@"relay-status"];
    mark.imageScaling = NSImageScaleProportionallyUpOrDown;
    mark.translatesAutoresizingMaskIntoConstraints = NO;
    NSTextField *brand = RelayLabel(@"Relay", 21, NSFontWeightSemibold, RelayColor(0x17211d));
    brand.translatesAutoresizingMaskIntoConstraints = NO;
    [sidebar addSubview:mark];
    [sidebar addSubview:brand];

    NSButton *newTask = RelayButton(@"New task", self, @selector(showComposer:), YES);
    newTask.image = [NSImage imageWithSystemSymbolName:@"plus" accessibilityDescription:@"New task"];
    newTask.imagePosition = NSImageLeading;
    newTask.alignment = NSTextAlignmentLeft;
    [sidebar addSubview:newTask];

    NSTextField *chats = RelayLabel(@"Conversations", 12, NSFontWeightMedium, RelayColor(0x59645f));
    chats.translatesAutoresizingMaskIntoConstraints = NO;
    [sidebar addSubview:chats];

    NSScrollView *historyScroll = [[NSScrollView alloc] init];
    historyScroll.hasVerticalScroller = YES;
    historyScroll.drawsBackground = NO;
    historyScroll.translatesAutoresizingMaskIntoConstraints = NO;
    NSTableView *table = [[NSTableView alloc] init];
    NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:@"history"];
    column.resizingMask = NSTableColumnAutoresizingMask;
    [table addTableColumn:column];
    table.headerView = nil;
    table.rowHeight = 50;
    table.backgroundColor = NSColor.clearColor;
    table.intercellSpacing = NSMakeSize(0, 4);
    table.selectionHighlightStyle = NSTableViewSelectionHighlightStyleRegular;
    table.delegate = self;
    table.dataSource = self;
    historyScroll.documentView = table;
    self.historyTable = table;
    [sidebar addSubview:historyScroll];

    NSButton *settings = RelayButton(@"Agent connections", self, @selector(showConnections:), NO);
    settings.image = [NSImage imageWithSystemSymbolName:@"gearshape" accessibilityDescription:@"Connections"];
    settings.imagePosition = NSImageLeading;
    settings.alignment = NSTextAlignmentLeft;
    [sidebar addSubview:settings];

    NSTextField *local = RelayLabel(@"Starting local engine…", 11, NSFontWeightRegular, RelayColor(0x65706b));
    local.translatesAutoresizingMaskIntoConstraints = NO;
    self.localStatus = local;
    [sidebar addSubview:local];

    RelaySurfaceView *sheet = [[RelaySurfaceView alloc] init];
    sheet.fillColor = NSColor.whiteColor;
    sheet.edgeColor = RelayColor(0xe2e8e4);
    sheet.radius = 15;
    sheet.translatesAutoresizingMaskIntoConstraints = NO;
    self.sheet = sheet;
    [self.view addSubview:sheet];

    NSView *topbar = [[NSView alloc] init];
    topbar.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:topbar];
    NSTextField *scope = RelayLabel(@"Local agent workspace", 12, NSFontWeightMedium, RelayColor(0x65706b));
    scope.translatesAutoresizingMaskIntoConstraints = NO;
    [topbar addSubview:scope];

    NSView *host = [[NSView alloc] init];
    host.translatesAutoresizingMaskIntoConstraints = NO;
    self.screenHost = host;
    [sheet addSubview:host];

    [NSLayoutConstraint activateConstraints:@[
        [sidebar.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor],
        [sidebar.topAnchor constraintEqualToAnchor:self.view.topAnchor],
        [sidebar.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor],
        [sidebar.widthAnchor constraintEqualToConstant:232],

        [mark.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:20],
        [mark.topAnchor constraintEqualToAnchor:sidebar.topAnchor constant:20],
        [mark.widthAnchor constraintEqualToConstant:28],
        [mark.heightAnchor constraintEqualToConstant:28],
        [brand.leadingAnchor constraintEqualToAnchor:mark.trailingAnchor constant:9],
        [brand.centerYAnchor constraintEqualToAnchor:mark.centerYAnchor],

        [newTask.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:14],
        [newTask.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor constant:-14],
        [newTask.topAnchor constraintEqualToAnchor:mark.bottomAnchor constant:26],
        [chats.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:20],
        [chats.topAnchor constraintEqualToAnchor:newTask.bottomAnchor constant:24],
        [historyScroll.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:10],
        [historyScroll.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor constant:-10],
        [historyScroll.topAnchor constraintEqualToAnchor:chats.bottomAnchor constant:10],
        [historyScroll.bottomAnchor constraintEqualToAnchor:settings.topAnchor constant:-16],
        [settings.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:14],
        [settings.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor constant:-14],
        [settings.bottomAnchor constraintEqualToAnchor:local.topAnchor constant:-9],
        [local.leadingAnchor constraintEqualToAnchor:sidebar.leadingAnchor constant:20],
        [local.trailingAnchor constraintEqualToAnchor:sidebar.trailingAnchor constant:-14],
        [local.bottomAnchor constraintEqualToAnchor:sidebar.bottomAnchor constant:-17],

        [topbar.leadingAnchor constraintEqualToAnchor:sidebar.trailingAnchor],
        [topbar.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor],
        [topbar.topAnchor constraintEqualToAnchor:self.view.topAnchor],
        [topbar.heightAnchor constraintEqualToConstant:48],
        [scope.leadingAnchor constraintEqualToAnchor:topbar.leadingAnchor constant:24],
        [scope.centerYAnchor constraintEqualToAnchor:topbar.centerYAnchor],

        [sheet.leadingAnchor constraintEqualToAnchor:sidebar.trailingAnchor],
        [sheet.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-8],
        [sheet.topAnchor constraintEqualToAnchor:topbar.bottomAnchor],
        [sheet.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor constant:-8],
        [host.leadingAnchor constraintEqualToAnchor:sheet.leadingAnchor],
        [host.trailingAnchor constraintEqualToAnchor:sheet.trailingAnchor],
        [host.topAnchor constraintEqualToAnchor:sheet.topAnchor],
        [host.bottomAnchor constraintEqualToAnchor:sheet.bottomAnchor]
    ]];
}

- (NSView *)labeledControl:(NSString *)label control:(NSView *)control width:(CGFloat)width {
    NSStackView *stack = [NSStackView stackViewWithViews:@[RelayLabel(label, 12, NSFontWeightMedium, RelayColor(0x4d5853)), control]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeLeading;
    stack.spacing = 7;
    if (width > 0) [control.widthAnchor constraintEqualToConstant:width].active = YES;
    return stack;
}

- (NSView *)buildComposer {
    NSView *container = [[NSView alloc] init];
    container.translatesAutoresizingMaskIntoConstraints = NO;
    NSLayoutGuide *contentGuide = [[NSLayoutGuide alloc] init];
    [container addLayoutGuide:contentGuide];

    NSTextField *title = RelayLabel(@"Agent workspace", 26, NSFontWeightSemibold, RelayColor(0x17211d));
    NSTextField *subtitle = RelayLabel(@"Plan a change, approve the work, and follow every handoff.", 14, NSFontWeightRegular, RelayColor(0x5e6964));
    title.translatesAutoresizingMaskIntoConstraints = NO;
    subtitle.translatesAutoresizingMaskIntoConstraints = NO;
    [container addSubview:title];
    [container addSubview:subtitle];

    NSPopUpButton *projects = [[NSPopUpButton alloc] init];
    projects.controlSize = NSControlSizeLarge;
    projects.translatesAutoresizingMaskIntoConstraints = NO;
    self.projectPopup = projects;
    NSButton *addProject = RelayButton(@"Add project…", self, @selector(addProject:), NO);
    NSStackView *projectRow = [NSStackView stackViewWithViews:@[projects, addProject]];
    projectRow.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    projectRow.spacing = 10;
    projectRow.distribution = NSStackViewDistributionFill;
    projectRow.translatesAutoresizingMaskIntoConstraints = NO;
    [projects.widthAnchor constraintGreaterThanOrEqualToConstant:320].active = YES;

    NSSegmentedControl *mode = [NSSegmentedControl segmentedControlWithLabels:@[@"Observe", @"Plan", @"Build & review"] trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(modeChanged:)];
    mode.selectedSegment = 2;
    mode.controlSize = NSControlSizeLarge;
    mode.selectedSegmentBezelColor = RelayColor(0x225b4d);
    mode.translatesAutoresizingMaskIntoConstraints = NO;
    self.modeControl = mode;

    NSTextView *editor = [[NSTextView alloc] init];
    editor.font = [NSFont systemFontOfSize:14];
    editor.textContainerInset = NSMakeSize(10, 10);
    editor.delegate = self;
    editor.drawsBackground = YES;
    editor.backgroundColor = NSColor.whiteColor;
    editor.textColor = RelayColor(0x17211d);
    NSScrollView *editorScroll = [[NSScrollView alloc] init];
    editorScroll.documentView = editor;
    editorScroll.hasVerticalScroller = YES;
    editorScroll.borderType = NSBezelBorder;
    editorScroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.taskEditor = editor;

    RelaySurfaceView *teamCard = [[RelaySurfaceView alloc] init];
    teamCard.fillColor = RelayColor(0xf8faf9);
    teamCard.edgeColor = RelayColor(0xe7ebe8);
    teamCard.radius = 10;
    teamCard.translatesAutoresizingMaskIntoConstraints = NO;
    NSTextField *teamTitle = RelayLabel(@"Your team", 15, NSFontWeightSemibold, RelayColor(0x17211d));
    teamTitle.translatesAutoresizingMaskIntoConstraints = NO;
    [teamCard addSubview:teamTitle];

    NSStackView *roles = [[NSStackView alloc] init];
    roles.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    roles.distribution = NSStackViewDistributionFillEqually;
    roles.spacing = 20;
    roles.translatesAutoresizingMaskIntoConstraints = NO;
    NSArray *roleNames = @[@"Observer", @"Builder", @"Reviewer"];
    NSArray *roleKeys = @[@"observer", @"builder", @"reviewer"];
    for (NSInteger index = 0; index < roleNames.count; index++) {
        NSPopUpButton *popup = [[NSPopUpButton alloc] init];
        [popup addItemsWithTitles:@[@"Claude Code", @"Codex"]];
        popup.controlSize = NSControlSizeRegular;
        self.rolePopups[roleKeys[index]] = popup;
        NSView *field = [self labeledControl:roleNames[index] control:popup width:0];
        [roles addArrangedSubview:field];
    }
    NSTextField *connection = RelayLabel(@"Checking your agent connections…", 11, NSFontWeightRegular, RelayColor(0x65706b));
    connection.translatesAutoresizingMaskIntoConstraints = NO;
    self.connectionSummary = connection;
    [teamCard addSubview:roles];
    [teamCard addSubview:connection];

    NSPopUpButton *rounds = [[NSPopUpButton alloc] init];
    [rounds addItemsWithTitles:@[@"1 round", @"2 rounds", @"3 rounds", @"4 rounds", @"5 rounds", @"Without limit"]];
    [rounds selectItemAtIndex:2];
    rounds.controlSize = NSControlSizeLarge;
    self.roundsPopup = rounds;
    NSPopUpButton *minutes = [[NSPopUpButton alloc] init];
    [minutes addItemsWithTitles:@[@"10 minutes", @"20 minutes", @"40 minutes", @"60 minutes", @"120 minutes", @"Without limit"]];
    [minutes selectItemAtIndex:1];
    minutes.controlSize = NSControlSizeLarge;
    self.minutesPopup = minutes;
    NSStackView *limits = [NSStackView stackViewWithViews:@[
        [self labeledControl:@"Review rounds" control:rounds width:150],
        [self labeledControl:@"Time limit" control:minutes width:150]
    ]];
    limits.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    limits.spacing = 12;
    limits.translatesAutoresizingMaskIntoConstraints = NO;

    NSButton *start = RelayButton(@"Start collaboration", self, @selector(startTask:), YES);
    [start.widthAnchor constraintEqualToConstant:170].active = YES;
    self.startButton = start;
    NSTextField *error = RelayLabel(@"", 12, NSFontWeightRegular, RelayColor(0xa82d36));
    error.maximumNumberOfLines = 2;
    error.translatesAutoresizingMaskIntoConstraints = NO;
    self.composerError = error;

    for (NSView *view in @[projectRow, mode, editorScroll, teamCard, limits, start, error]) {
        view.translatesAutoresizingMaskIntoConstraints = NO;
        [container addSubview:view];
    }
    NSTextField *projectLabel = RelayLabel(@"Project", 12, NSFontWeightMedium, RelayColor(0x4d5853));
    NSTextField *modeLabel = RelayLabel(@"Task mode", 12, NSFontWeightMedium, RelayColor(0x4d5853));
    NSTextField *taskLabel = RelayLabel(@"What should your team do?", 12, NSFontWeightMedium, RelayColor(0x4d5853));
    for (NSTextField *label in @[projectLabel, modeLabel, taskLabel]) { label.translatesAutoresizingMaskIntoConstraints = NO; [container addSubview:label]; }

    NSLayoutConstraint *preferredWideWidth = [contentGuide.widthAnchor constraintEqualToConstant:1120];
    preferredWideWidth.priority = NSLayoutPriorityDefaultHigh + 1;
    NSLayoutConstraint *preferredWindowWidth = [contentGuide.widthAnchor constraintEqualToAnchor:container.widthAnchor constant:-60];
    preferredWindowWidth.priority = NSLayoutPriorityDefaultHigh;

    [NSLayoutConstraint activateConstraints:@[
        [contentGuide.centerXAnchor constraintEqualToAnchor:container.centerXAnchor],
        [contentGuide.leadingAnchor constraintGreaterThanOrEqualToAnchor:container.leadingAnchor constant:30],
        [contentGuide.trailingAnchor constraintLessThanOrEqualToAnchor:container.trailingAnchor constant:-30],
        [contentGuide.widthAnchor constraintLessThanOrEqualToConstant:1120],
        preferredWideWidth,
        preferredWindowWidth,

        [title.leadingAnchor constraintEqualToAnchor:contentGuide.leadingAnchor],
        [title.trailingAnchor constraintLessThanOrEqualToAnchor:contentGuide.trailingAnchor],
        [title.topAnchor constraintEqualToAnchor:container.topAnchor constant:24],
        [subtitle.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [subtitle.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:6],

        [projectLabel.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [projectLabel.topAnchor constraintEqualToAnchor:subtitle.bottomAnchor constant:22],
        [projectRow.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [projectRow.topAnchor constraintEqualToAnchor:projectLabel.bottomAnchor constant:7],

        [modeLabel.leadingAnchor constraintEqualToAnchor:projectRow.trailingAnchor constant:28],
        [modeLabel.topAnchor constraintEqualToAnchor:projectLabel.topAnchor],
        [mode.leadingAnchor constraintEqualToAnchor:modeLabel.leadingAnchor],
        [mode.topAnchor constraintEqualToAnchor:modeLabel.bottomAnchor constant:7],
        [mode.trailingAnchor constraintLessThanOrEqualToAnchor:contentGuide.trailingAnchor],

        [taskLabel.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [taskLabel.topAnchor constraintEqualToAnchor:projectRow.bottomAnchor constant:18],
        [editorScroll.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [editorScroll.trailingAnchor constraintEqualToAnchor:contentGuide.trailingAnchor],
        [editorScroll.topAnchor constraintEqualToAnchor:taskLabel.bottomAnchor constant:7],
        [editorScroll.heightAnchor constraintEqualToConstant:145],

        [teamCard.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [teamCard.trailingAnchor constraintEqualToAnchor:editorScroll.trailingAnchor],
        [teamCard.topAnchor constraintEqualToAnchor:editorScroll.bottomAnchor constant:16],
        [teamCard.heightAnchor constraintEqualToConstant:116],
        [teamTitle.leadingAnchor constraintEqualToAnchor:teamCard.leadingAnchor constant:18],
        [teamTitle.topAnchor constraintEqualToAnchor:teamCard.topAnchor constant:15],
        [roles.leadingAnchor constraintEqualToAnchor:teamTitle.leadingAnchor],
        [roles.trailingAnchor constraintEqualToAnchor:teamCard.trailingAnchor constant:-18],
        [roles.topAnchor constraintEqualToAnchor:teamTitle.bottomAnchor constant:12],
        [connection.leadingAnchor constraintEqualToAnchor:teamTitle.leadingAnchor],
        [connection.bottomAnchor constraintEqualToAnchor:teamCard.bottomAnchor constant:-10],

        [limits.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [limits.topAnchor constraintEqualToAnchor:teamCard.bottomAnchor constant:16],
        [limits.heightAnchor constraintEqualToConstant:50],
        [start.trailingAnchor constraintEqualToAnchor:editorScroll.trailingAnchor],
        [start.centerYAnchor constraintEqualToAnchor:limits.centerYAnchor],
        [error.trailingAnchor constraintEqualToAnchor:start.trailingAnchor],
        [error.bottomAnchor constraintEqualToAnchor:start.topAnchor constant:-7],
        [error.leadingAnchor constraintGreaterThanOrEqualToAnchor:limits.trailingAnchor constant:18]
    ]];
    return container;
}

- (NSView *)buildDetail {
    NSView *container = [[NSView alloc] init];
    container.translatesAutoresizingMaskIntoConstraints = NO;
    NSTextField *title = RelayLabel(@"", 24, NSFontWeightSemibold, RelayColor(0x17211d));
    title.translatesAutoresizingMaskIntoConstraints = NO;
    self.detailTitle = title;
    NSTextField *subtitle = RelayLabel(@"", 12, NSFontWeightRegular, RelayColor(0x65706b));
    subtitle.translatesAutoresizingMaskIntoConstraints = NO;
    self.detailSubtitle = subtitle;
    NSTextField *status = RelayLabel(@"", 12, NSFontWeightMedium, RelayColor(0x225b4d));
    status.alignment = NSTextAlignmentCenter;
    status.wantsLayer = YES;
    status.layer.backgroundColor = RelayColor(0xe9f3ef).CGColor;
    status.layer.cornerRadius = 6;
    status.translatesAutoresizingMaskIntoConstraints = NO;
    self.statusLabel = status;

    NSButton *pause = RelayButton(@"Pause handoffs", self, @selector(togglePause:), NO);
    NSButton *stop = RelayButton(@"Stop", self, @selector(stopTask:), NO);
    self.pauseButton = pause;
    self.stopButton = stop;
    NSStackView *actions = [NSStackView stackViewWithViews:@[pause, stop]];
    actions.orientation = NSUserInterfaceLayoutOrientationHorizontal;
    actions.spacing = 8;
    actions.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *decision = [[NSStackView alloc] init];
    decision.orientation = NSUserInterfaceLayoutOrientationVertical;
    decision.alignment = NSLayoutAttributeLeading;
    decision.spacing = 9;
    decision.translatesAutoresizingMaskIntoConstraints = NO;
    self.decisionStack = decision;

    NSTextView *transcript = [[NSTextView alloc] init];
    transcript.editable = NO;
    transcript.selectable = YES;
    transcript.richText = YES;
    transcript.drawsBackground = NO;
    transcript.textContainerInset = NSMakeSize(2, 12);
    transcript.textContainer.lineFragmentPadding = 0;
    NSScrollView *scroll = [[NSScrollView alloc] init];
    scroll.documentView = transcript;
    scroll.hasVerticalScroller = YES;
    scroll.drawsBackground = NO;
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.transcript = transcript;

    for (NSView *view in @[title, subtitle, status, actions, decision, scroll]) [container addSubview:view];
    [NSLayoutConstraint activateConstraints:@[
        [title.leadingAnchor constraintEqualToAnchor:container.leadingAnchor constant:30],
        [title.topAnchor constraintEqualToAnchor:container.topAnchor constant:27],
        [title.trailingAnchor constraintLessThanOrEqualToAnchor:actions.leadingAnchor constant:-20],
        [subtitle.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [subtitle.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:6],
        [status.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [status.topAnchor constraintEqualToAnchor:subtitle.bottomAnchor constant:14],
        [status.heightAnchor constraintEqualToConstant:25],
        [status.widthAnchor constraintGreaterThanOrEqualToConstant:94],
        [actions.trailingAnchor constraintEqualToAnchor:container.trailingAnchor constant:-30],
        [actions.topAnchor constraintEqualToAnchor:container.topAnchor constant:27],
        [decision.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [decision.trailingAnchor constraintEqualToAnchor:container.trailingAnchor constant:-30],
        [decision.topAnchor constraintEqualToAnchor:status.bottomAnchor constant:17],
        [scroll.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [scroll.trailingAnchor constraintEqualToAnchor:container.trailingAnchor constant:-30],
        [scroll.topAnchor constraintEqualToAnchor:decision.bottomAnchor constant:13],
        [scroll.bottomAnchor constraintEqualToAnchor:container.bottomAnchor constant:-22]
    ]];
    return container;
}

- (void)installScreen:(NSView *)screen {
    for (NSView *view in self.screenHost.subviews) [view removeFromSuperview];
    [self.screenHost addSubview:screen];
    [NSLayoutConstraint activateConstraints:@[
        [screen.leadingAnchor constraintEqualToAnchor:self.screenHost.leadingAnchor],
        [screen.trailingAnchor constraintEqualToAnchor:self.screenHost.trailingAnchor],
        [screen.topAnchor constraintEqualToAnchor:self.screenHost.topAnchor],
        [screen.bottomAnchor constraintEqualToAnchor:self.screenHost.bottomAnchor]
    ]];
}

- (void)showComposer:(id)sender {
    self.selectedRunID = nil;
    [self.historyTable deselectAll:nil];
    if (!self.composer) self.composer = [self buildComposer];
    [self installScreen:self.composer];
}

- (void)showSelectedRun {
    if (!self.detail) self.detail = [self buildDetail];
    [self installScreen:self.detail];
    [self renderSelectedRun];
}

- (void)initialLoad {
    self.localStatus.stringValue = @"Local engine connected";
    [self refreshState];
    [self refreshProjects];
    [self.api get:@"/api/teams" completion:^(NSDictionary *json, NSError *error) {
        if (!error) {
            self.defaultTeam = json[@"default"];
            [self applyDefaultTeam];
        }
    }];
    [self refreshConnections];
    self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:1.2 target:self selector:@selector(refreshState) userInfo:nil repeats:YES];
}

- (void)refreshState {
    [self.api get:@"/api/state" completion:^(NSDictionary *json, NSError *error) {
        if (error) {
            self.localStatus.stringValue = @"Reconnecting to local engine…";
            return;
        }
        self.localStatus.stringValue = @"Local engine connected";
        self.api.token = json[@"token"];
        self.runs = [json[@"runs"] isKindOfClass:NSArray.class] ? json[@"runs"] : @[];
        [self.historyTable reloadData];
        if (self.selectedRunID) [self renderSelectedRun];
    }];
}

- (void)refreshProjects {
    [self.api get:@"/api/projects" completion:^(NSDictionary *json, NSError *error) {
        if (error) return;
        self.projects = [json[@"projects"] isKindOfClass:NSArray.class] ? json[@"projects"] : @[];
        [self.projectPopup removeAllItems];
        if (!self.projects.count) [self.projectPopup addItemWithTitle:@"No projects yet"];
        for (NSDictionary *project in self.projects) {
            [self.projectPopup addItemWithTitle:project[@"name"] ?: @"Project"];
            self.projectPopup.lastItem.representedObject = project[@"path"] ?: @"";
            self.projectPopup.lastItem.enabled = [project[@"exists"] boolValue];
        }
    }];
}

- (void)refreshConnections {
    [self.api get:@"/api/connections" completion:^(NSDictionary *json, NSError *error) {
        if (error) {
            self.connectionSummary.stringValue = @"Connection check unavailable";
            return;
        }
        self.connections = json;
        NSDictionary *claude = json[@"claude"];
        NSDictionary *codex = json[@"codex"];
        NSString *claudeText = [claude[@"signed_in"] boolValue] ? @"Claude signed in" : ([claude[@"installed"] boolValue] ? @"Claude needs sign-in" : @"Claude not installed");
        NSString *codexText = [codex[@"signed_in"] boolValue] ? @"Codex signed in" : ([codex[@"installed"] boolValue] ? @"Codex needs sign-in" : @"Codex not installed");
        self.connectionSummary.stringValue = [NSString stringWithFormat:@"%@   ·   %@", claudeText, codexText];
    }];
}

- (void)applyDefaultTeam {
    NSDictionary *roles = self.defaultTeam[@"roles"];
    for (NSString *key in self.rolePopups) {
        NSString *provider = roles[key][@"provider"];
        [self.rolePopups[key] selectItemAtIndex:[provider isEqualToString:@"codex"] ? 1 : 0];
    }
}

- (NSDictionary *)currentTeam {
    NSMutableDictionary *roles = [NSMutableDictionary dictionary];
    for (NSString *key in self.rolePopups) {
        NSString *provider = self.rolePopups[key].indexOfSelectedItem == 1 ? @"codex" : @"claude";
        roles[key] = @{ @"provider": provider, @"model": @"", @"effort": @"", @"instructions": @"" };
    }
    if (roles.count != 3 && self.defaultTeam) return self.defaultTeam;
    return @{ @"name": @"Native Relay team", @"roles": roles };
}

- (void)addProject:(id)sender {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.canChooseDirectories = YES;
    panel.canChooseFiles = NO;
    panel.allowsMultipleSelection = NO;
    panel.prompt = @"Add Project";
    [panel beginSheetModalForWindow:self.view.window completionHandler:^(NSModalResponse result) {
        if (result != NSModalResponseOK) return;
        NSURL *url = panel.URL;
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Name this project";
        alert.informativeText = url.path;
        [alert addButtonWithTitle:@"Save"];
        [alert addButtonWithTitle:@"Cancel"];
        NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 24)];
        field.stringValue = url.lastPathComponent;
        alert.accessoryView = field;
        [alert beginSheetModalForWindow:self.view.window completionHandler:^(NSModalResponse response) {
            if (response != NSAlertFirstButtonReturn || !field.stringValue.length) return;
            [self.api post:@"/api/projects/save" body:@{ @"name": field.stringValue, @"path": url.path } completion:^(NSDictionary *json, NSError *error) {
                if (error) [self showError:error.localizedDescription];
                else [self refreshProjects];
            }];
        }];
    }];
}

- (void)modeChanged:(id)sender {
    BOOL build = self.modeControl.selectedSegment == 2;
    self.roundsPopup.enabled = build;
    self.startButton.title = build ? @"Start collaboration" : (self.modeControl.selectedSegment == 1 ? @"Create plan" : @"Start observation");
}

- (void)startTask:(id)sender {
    NSString *task = [self.taskEditor.string stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *project = self.projectPopup.selectedItem.representedObject;
    if (!task.length || !project.length) {
        self.composerError.stringValue = !project.length ? @"Add or choose a project first." : @"Describe what you want your team to do.";
        return;
    }
    NSArray *modes = @[@"observe", @"plan", @"build"];
    NSArray *roundValues = @[@1, @2, @3, @4, @5, @0];
    NSArray *minuteValues = @[@10, @20, @40, @60, @120, @0];
    NSDictionary *body = @{
        @"task": task,
        @"project": project,
        @"mode": modes[self.modeControl.selectedSegment],
        @"team": [self currentTeam],
        @"rounds": roundValues[self.roundsPopup.indexOfSelectedItem],
        @"minutes": minuteValues[self.minutesPopup.indexOfSelectedItem],
        @"images": @[],
        @"demo": @NO
    };
    self.startButton.enabled = NO;
    self.composerError.stringValue = @"";
    [self.api post:@"/api/run" body:body completion:^(NSDictionary *json, NSError *error) {
        self.startButton.enabled = YES;
        if (error) {
            self.composerError.stringValue = error.localizedDescription;
            return;
        }
        self.selectedRunID = json[@"id"];
        [self showSelectedRun];
        [self refreshState];
    }];
}

- (NSDictionary *)selectedRun {
    for (NSDictionary *run in self.runs) if ([run[@"id"] isEqualToString:self.selectedRunID]) return run;
    return nil;
}

- (NSString *)friendlyStatus:(NSString *)status {
    NSDictionary *names = @{
        @"queued": @"Preparing", @"preparing": @"Preparing", @"observing": @"Observer working",
        @"awaiting_clarification": @"Needs your answers", @"awaiting_approval": @"Plan ready for approval",
        @"building": @"Builder working", @"reviewing": @"Reviewer checking", @"fixing": @"Builder refining",
        @"done": @"Complete", @"needs_attention": @"Needs attention", @"failed": @"Could not finish",
        @"stopped": @"Stopped", @"interrupted": @"Interrupted"
    };
    return names[status] ?: status.capitalizedString;
}

- (BOOL)isTerminal:(NSString *)status {
    return [@[@"done", @"needs_attention", @"failed", @"stopped", @"interrupted"] containsObject:status];
}

- (void)clearDecisionStack {
    for (NSView *view in self.decisionStack.arrangedSubviews.copy) {
        [self.decisionStack removeArrangedSubview:view];
        [view removeFromSuperview];
    }
    [self.answerFields removeAllObjects];
}

- (void)renderSelectedRun {
    NSDictionary *run = [self selectedRun];
    if (!run || !self.detail) return;
    NSString *task = run[@"conversation_title"] ?: run[@"task"] ?: @"Relay task";
    self.detailTitle.stringValue = task;
    NSString *mode = run[@"mode"] ?: @"build";
    self.detailSubtitle.stringValue = [NSString stringWithFormat:@"%@ · round %@ · %@ minute limit", mode.capitalizedString, run[@"round"] ?: @0, run[@"minutes"] ?: @0];
    NSString *status = run[@"status"] ?: @"queued";
    self.statusLabel.stringValue = [NSString stringWithFormat:@"  %@  ", [self friendlyStatus:status]];
    BOOL active = ![self isTerminal:status];
    self.pauseButton.hidden = !active || [@[@"awaiting_approval", @"awaiting_clarification"] containsObject:status];
    self.stopButton.hidden = !active;
    self.pauseButton.title = [run[@"paused"] boolValue] ? @"Resume handoffs" : @"Pause handoffs";
    [self clearDecisionStack];

    if ([status isEqualToString:@"awaiting_approval"] && [run[@"plan"] isKindOfClass:NSDictionary.class]) {
        NSDictionary *plan = run[@"plan"];
        NSTextField *heading = RelayLabel(@"Review the plan before editing", 16, NSFontWeightSemibold, RelayColor(0x17211d));
        heading.maximumNumberOfLines = 2;
        NSTextField *summary = [NSTextField wrappingLabelWithString:plan[@"summary"] ?: @""];
        summary.font = [NSFont systemFontOfSize:13];
        summary.textColor = RelayColor(0x3f4944);
        summary.maximumNumberOfLines = 5;
        NSButton *reject = RelayButton(@"Reject plan", self, @selector(rejectPlan:), NO);
        NSButton *approve = RelayButton(@"Approve & start building", self, @selector(approvePlan:), YES);
        NSStackView *buttons = [NSStackView stackViewWithViews:@[reject, approve]];
        buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal;
        buttons.spacing = 8;
        [self.decisionStack addArrangedSubview:heading];
        [self.decisionStack addArrangedSubview:summary];
        [self.decisionStack addArrangedSubview:buttons];
    } else if ([status isEqualToString:@"awaiting_clarification"] && [run[@"clarification"] isKindOfClass:NSDictionary.class]) {
        NSTextField *heading = RelayLabel(@"A few details before the plan", 16, NSFontWeightSemibold, RelayColor(0x17211d));
        [self.decisionStack addArrangedSubview:heading];
        for (NSDictionary *question in run[@"clarification"][@"questions"]) {
            NSTextField *label = [NSTextField wrappingLabelWithString:question[@"question"] ?: @"Question"];
            label.font = [NSFont systemFontOfSize:13 weight:NSFontWeightMedium];
            NSTextField *field = [[NSTextField alloc] init];
            field.placeholderString = [question[@"options"] isKindOfClass:NSArray.class] ? [question[@"options"] componentsJoinedByString:@" · "] : @"Your answer";
            [field.widthAnchor constraintEqualToConstant:620].active = YES;
            [field.heightAnchor constraintEqualToConstant:32].active = YES;
            NSString *questionID = question[@"id"] ?: NSUUID.UUID.UUIDString;
            self.answerFields[questionID] = field;
            [self.decisionStack addArrangedSubview:label];
            [self.decisionStack addArrangedSubview:field];
        }
        [self.decisionStack addArrangedSubview:RelayButton(@"Send answers & update plan", self, @selector(sendAnswers:), YES)];
    }
    [self renderTranscript:run];
}

- (void)appendText:(NSString *)text attributes:(NSDictionary *)attributes to:(NSMutableAttributedString *)target {
    if (!text.length) return;
    [target appendAttributedString:[[NSAttributedString alloc] initWithString:text attributes:attributes]];
}

- (void)renderTranscript:(NSDictionary *)run {
    NSMutableAttributedString *text = [[NSMutableAttributedString alloc] init];
    NSColor *ink = RelayColor(0x26312c);
    NSColor *muted = RelayColor(0x65706b);
    NSDictionary *body = @{NSFontAttributeName: [NSFont systemFontOfSize:13], NSForegroundColorAttributeName: ink};
    NSDictionary *meta = @{NSFontAttributeName: [NSFont systemFontOfSize:11], NSForegroundColorAttributeName: muted};
    NSDictionary *author = @{NSFontAttributeName: [NSFont systemFontOfSize:13 weight:NSFontWeightSemibold], NSForegroundColorAttributeName: RelayColor(0x225b4d)};
    NSArray *events = [run[@"events"] isKindOfClass:NSArray.class] ? run[@"events"] : @[];
    NSInteger start = MAX(0, (NSInteger)events.count - 100);
    for (NSInteger index = start; index < events.count; index++) {
        NSDictionary *event = events[index];
        NSString *agent = event[@"agent"] ?: @"Relay";
        NSString *kind = event[@"kind"] ?: @"message";
        NSString *message = event[@"message"] ?: @"";
        [self appendText:[NSString stringWithFormat:@"%@", agent] attributes:author to:text];
        [self appendText:[NSString stringWithFormat:@"   %@\n", [kind stringByReplacingOccurrencesOfString:@"_" withString:@" "]] attributes:meta to:text];
        if ([kind isEqualToString:@"tool"] || [kind isEqualToString:@"log"]) {
            if (message.length > 1200) message = [[message substringToIndex:1200] stringByAppendingString:@"…"];
            [self appendText:[message stringByAppendingString:@"\n\n"] attributes:@{NSFontAttributeName: [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular], NSForegroundColorAttributeName: muted} to:text];
        } else {
            [self appendText:[message stringByAppendingString:@"\n\n"] attributes:body to:text];
        }
    }
    NSString *summary = run[@"summary"];
    if (summary.length && [self isTerminal:run[@"status"]]) {
        [self appendText:@"Final result\n" attributes:author to:text];
        [self appendText:[summary stringByAppendingString:@"\n"] attributes:body to:text];
    }
    self.transcript.textStorage.attributedString = text;
}

- (void)postControl:(NSString *)path extra:(NSDictionary *)extra {
    NSDictionary *run = [self selectedRun];
    if (!run) return;
    NSMutableDictionary *body = [@{ @"id": run[@"id"] } mutableCopy];
    [body addEntriesFromDictionary:extra ?: @{}];
    [self.api post:path body:body completion:^(NSDictionary *json, NSError *error) {
        if (error) [self showError:error.localizedDescription];
        [self refreshState];
    }];
}

- (void)approvePlan:(id)sender {
    NSDictionary *run = [self selectedRun];
    [self postControl:@"/api/approve-plan" extra:@{ @"plan_id": run[@"plan"][@"id"] ?: @"" }];
}
- (void)rejectPlan:(id)sender { [self postControl:@"/api/stop" extra:@{}]; }
- (void)stopTask:(id)sender { [self postControl:@"/api/stop" extra:@{}]; }
- (void)togglePause:(id)sender {
    NSDictionary *run = [self selectedRun];
    [self postControl:[run[@"paused"] boolValue] ? @"/api/resume" : @"/api/pause" extra:@{}];
}
- (void)sendAnswers:(id)sender {
    NSDictionary *run = [self selectedRun];
    NSMutableDictionary *answers = [NSMutableDictionary dictionary];
    for (NSString *key in self.answerFields) {
        NSString *answer = [self.answerFields[key].stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        if (!answer.length) { [self showError:@"Answer every question before continuing."]; return; }
        answers[key] = answer;
    }
    [self postControl:@"/api/answer-clarification" extra:@{ @"clarification_id": run[@"clarification"][@"id"] ?: @"", @"answers": answers }];
}

- (void)showConnections:(id)sender {
    NSDictionary *claude = self.connections[@"claude"] ?: @{};
    NSDictionary *codex = self.connections[@"codex"] ?: @{};
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Agent connections";
    alert.informativeText = [NSString stringWithFormat:@"Claude Code\n%@\n\nCodex\n%@\n\nRelay uses the sign-ins already configured on this Mac.", claude[@"message"] ?: @"Checking…", codex[@"message"] ?: @"Checking…"];
    [alert addButtonWithTitle:@"Refresh"];
    [alert addButtonWithTitle:@"Done"];
    [alert beginSheetModalForWindow:self.view.window completionHandler:^(NSModalResponse response) {
        if (response == NSAlertFirstButtonReturn) [self refreshConnections];
    }];
}

- (void)showError:(NSString *)message {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Relay needs your attention";
    alert.informativeText = message ?: @"Something went wrong.";
    alert.alertStyle = NSAlertStyleWarning;
    [alert beginSheetModalForWindow:self.view.window completionHandler:nil];
}

- (NSInteger)numberOfRowsInTableView:(NSTableView *)tableView { return self.runs.count; }
- (NSView *)tableView:(NSTableView *)tableView viewForTableColumn:(NSTableColumn *)tableColumn row:(NSInteger)row {
    RelayHistoryCell *cell = [tableView makeViewWithIdentifier:@"RelayHistoryCell" owner:self];
    if (!cell) {
        cell = [[RelayHistoryCell alloc] initWithFrame:NSMakeRect(0, 0, tableView.bounds.size.width, 50)];
        cell.identifier = @"RelayHistoryCell";
    }
    NSDictionary *run = self.runs[row];
    NSString *title = run[@"conversation_title"] ?: run[@"task"] ?: @"Relay task";
    cell.textField.stringValue = title;
    cell.subtitle.stringValue = [self friendlyStatus:run[@"status"] ?: @""];
    return cell;
}
- (void)tableViewSelectionDidChange:(NSNotification *)notification {
    NSInteger row = self.historyTable.selectedRow;
    if (row < 0 || row >= self.runs.count) return;
    self.selectedRunID = self.runs[row][@"id"];
    [self showSelectedRun];
}
- (void)textDidChange:(NSNotification *)notification {
    if (notification.object == self.taskEditor) self.composerError.stringValue = @"";
}
- (void)dealloc { [self.pollTimer invalidate]; }
@end

@interface RelayAppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSTask *server;
@property(nonatomic, strong) NSMutableString *outputBuffer;
@property(nonatomic, strong) NSMutableString *errorBuffer;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic) BOOL quitting;
@property(nonatomic) BOOL mayTerminate;
@end

static RelayAppDelegate *RelayApplicationDelegate;

@implementation RelayAppDelegate
- (instancetype)init {
    self = [super init];
    if (self) { _outputBuffer = [NSMutableString string]; _errorBuffer = [NSMutableString string]; }
    return self;
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSMenu *mainMenu = [[NSMenu alloc] init];
    NSMenuItem *applicationItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:applicationItem];
    NSMenu *applicationMenu = [[NSMenu alloc] initWithTitle:@"Relay"];
    [applicationMenu addItemWithTitle:@"About Relay" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
    [applicationMenu addItem:[NSMenuItem separatorItem]];
    [applicationMenu addItemWithTitle:@"Hide Relay" action:@selector(hide:) keyEquivalent:@"h"];
    [applicationMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *quitItem = [[NSMenuItem alloc] initWithTitle:@"Quit Relay" action:@selector(terminate:) keyEquivalent:@"q"];
    quitItem.target = NSApp;
    [applicationMenu addItem:quitItem];
    applicationItem.submenu = applicationMenu;
    NSApp.mainMenu = mainMenu;
    [self startServer];
}
- (void)startServer {
    NSURL *resourceURL = NSBundle.mainBundle.resourceURL;
    NSURL *executable = [resourceURL URLByAppendingPathComponent:@"RelayServer"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:executable.path]) { [self fatal:@"Relay's engine is missing."]; return; }
    NSTask *process = [[NSTask alloc] init];
    NSPipe *output = [NSPipe pipe], *errors = [NSPipe pipe];
    process.executableURL = executable;
    process.arguments = @[@"--port", @"0"];
    process.standardOutput = output;
    process.standardError = errors;
    process.currentDirectoryURL = resourceURL;
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
    process.terminationHandler = ^(NSTask *task) { dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf serverStopped:task.terminationStatus]; }); };
    NSError *error = nil;
    if ([process launchAndReturnError:&error]) self.server = process;
    else [self fatal:[NSString stringWithFormat:@"Relay could not start: %@", error.localizedDescription]];
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
            if (url) [self openNativeWorkspace:url];
        }
    }
}
- (void)openNativeWorkspace:(NSURL *)url {
    RelayAPIClient *api = [[RelayAPIClient alloc] init];
    api.baseURL = url;
    RelayWorkspaceController *controller = [[RelayWorkspaceController alloc] initWithAPI:api];
    NSRect frame = NSMakeRect(0, 0, 1180, 760);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:frame
                                                  styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable | NSWindowStyleMaskFullSizeContentView
                                                    backing:NSBackingStoreBuffered defer:NO];
    window.title = @"Relay";
    window.titleVisibility = NSWindowTitleHidden;
    window.titlebarAppearsTransparent = YES;
    window.movableByWindowBackground = YES;
    window.minSize = NSMakeSize(960, 640);
    window.contentViewController = controller;
    window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
    [window center];
    [window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    self.window = window;
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) [self.window makeKeyAndOrderFront:nil];
    return YES;
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
- (void)serverStopped:(int)status {
    self.server = nil;
    if (self.quitting) { self.mayTerminate = YES; [NSApp terminate:nil]; return; }
    NSString *details = [self.errorBuffer stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    [self fatal:details.length ? details : [NSString stringWithFormat:@"Relay's local engine stopped unexpectedly (status %d).", status]];
}
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
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (self.mayTerminate || !self.server.running) return NSTerminateNow;
    if (!self.quitting) { self.quitting = YES; [self.server terminate]; }
    return NSTerminateCancel;
}
@end

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
