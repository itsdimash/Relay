#import "RelayActions.h"

#import <ApplicationServices/ApplicationServices.h>

static const NSUInteger RelayMaxTypedCharacters = 500;
static const NSUInteger RelayKeyChunk = 16;            // UTF-16 units in one key event
static const NSTimeInterval RelayTypeDelay = 0.4;      // the panel steps away and the app takes the keyboard back first

static NSRunningApplication *RelayLastOtherApplication; // the last app in front that was not Relay

static BOOL RelayIsSelf(NSRunningApplication *application) {
    return application.processIdentifier == NSProcessInfo.processInfo.processIdentifier;
}

@implementation RelayActions

+ (void)initialize {
    if (self != RelayActions.class) return;
    NSRunningApplication *front = NSWorkspace.sharedWorkspace.frontmostApplication;
    if (front && !RelayIsSelf(front)) RelayLastOtherApplication = front;
    [NSWorkspace.sharedWorkspace.notificationCenter addObserverForName:NSWorkspaceDidActivateApplicationNotification
                                                                object:nil
                                                                 queue:NSOperationQueue.mainQueue
                                                            usingBlock:^(NSNotification *note) {
        NSRunningApplication *application = note.userInfo[NSWorkspaceApplicationKey];
        if ([application isKindOfClass:NSRunningApplication.class] && !RelayIsSelf(application)) RelayLastOtherApplication = application;
    }];
}

+ (NSRunningApplication *)workingApplication {
    NSRunningApplication *front = NSWorkspace.sharedWorkspace.frontmostApplication;
    if (front && !RelayIsSelf(front)) return front;
    NSRunningApplication *last = RelayLastOtherApplication;
    return (last && !last.terminated) ? last : nil;
}

#pragma mark - Opening an app

+ (NSString *)plainName:(NSString *)name {
    return [name stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
}

// The installed app that has this name: the same name first (ignoring case and accents), then the one app that has it in its name.
+ (nullable NSURL *)applicationNamed:(NSString *)name {
    NSString *wanted = [self plainName:name];
    if (wanted.length == 0 || wanted.length > 60 || [wanted containsString:@"/"]) return nil;
    NSFileManager *files = NSFileManager.defaultManager;
    NSArray<NSString *> *folders = @[
        @"/Applications", @"/Applications/Utilities", @"/System/Applications", @"/System/Applications/Utilities",
        [NSHomeDirectory() stringByAppendingPathComponent:@"Applications"],
    ];
    NSStringCompareOptions loose = NSCaseInsensitiveSearch | NSDiacriticInsensitiveSearch;
    NSMutableArray<NSURL *> *partial = [NSMutableArray array];
    for (NSString *folder in folders) {
        for (NSString *file in [files contentsOfDirectoryAtPath:folder error:nil]) {
            if (![file.pathExtension.lowercaseString isEqualToString:@"app"]) continue;
            NSString *base = file.stringByDeletingPathExtension;
            NSURL *url = [NSURL fileURLWithPath:[folder stringByAppendingPathComponent:file]];
            if ([base compare:wanted options:loose] == NSOrderedSame) return url;
            if (wanted.length >= 3 && [base rangeOfString:wanted options:loose].location != NSNotFound) [partial addObject:url];
        }
    }
    if ([wanted compare:@"Finder" options:loose] == NSOrderedSame) return [NSURL fileURLWithPath:@"/System/Library/CoreServices/Finder.app"];
    return partial.count == 1 ? partial.firstObject : nil; // two apps that both fit: better to ask again than to guess
}

+ (void)openApplicationNames:(NSArray<NSString *> *)names done:(RelayActionDone)done {
    NSURL *found = nil;
    for (id name in names) {
        if (![name isKindOfClass:NSString.class]) continue;
        found = [self applicationNamed:name];
        if (found) break;
    }
    if (!found) {
        done(@"missing", @"");
        return;
    }
    NSString *title = [[NSFileManager.defaultManager displayNameAtPath:found.path] stringByDeletingPathExtension];
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.activates = YES;
    [NSWorkspace.sharedWorkspace openApplicationAtURL:found configuration:configuration completionHandler:^(NSRunningApplication *application, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{ done(error ? @"failed" : @"opened", title ?: @""); });
    }];
}

#pragma mark - Telegram

+ (void)draftTelegram:(NSString *)text done:(RelayActionDone)done {
    NSString *words = [self plainName:text ?: @""];
    if (words.length == 0 || words.length > RelayMaxTypedCharacters * 4) {
        done(@"failed", @"");
        return;
    }
    // Telegram documents one way to share: tg://msg_url, where "url" is required and is put into the message field. A draft that is
    // only words goes in "url" (a link without it opens nothing, and the older tg://msg?text= form is not in the documentation).
    // Only the plainest characters stay as they are: a "+" or "&" in the words must not be read as part of the link.
    NSCharacterSet *plain = [NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"];
    NSString *encoded = [words stringByAddingPercentEncodingWithAllowedCharacters:plain];
    NSURL *link = encoded ? [NSURL URLWithString:[@"tg://msg_url?url=" stringByAppendingString:encoded]] : nil;
    NSURL *telegram = link ? [NSWorkspace.sharedWorkspace URLForApplicationToOpenURL:link] : nil;
    if (!link) {
        done(@"failed", @"");
        return;
    }
    if (!telegram) {
        done(@"missing", @"Telegram");
        return;
    }
    // Not every Telegram shows the words from the link, so they are also on the clipboard: pick a chat and paste.
    [NSPasteboard.generalPasteboard clearContents];
    [NSPasteboard.generalPasteboard setString:words forType:NSPasteboardTypeString];
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.activates = YES;
    [NSWorkspace.sharedWorkspace openURLs:@[link] withApplicationAtURL:telegram configuration:configuration completionHandler:^(NSRunningApplication *application, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{ done(error ? @"failed" : @"opened", @"Telegram"); });
    }];
}

#pragma mark - Typing

+ (BOOL)accessAllowedAsking:(BOOL)ask {
    NSDictionary *options = @{ (__bridge NSString *)kAXTrustedCheckOptionPrompt: @(ask) };
    return AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
}

// One line, no control characters, never longer than the page allows.
+ (NSString *)oneLine:(NSString *)text {
    NSMutableString *line = [NSMutableString string];
    BOOL space = NO;
    for (NSUInteger i = 0; i < text.length && line.length < RelayMaxTypedCharacters; i++) {
        unichar c = [text characterAtIndex:i];
        if ([NSCharacterSet.controlCharacterSet characterIsMember:c] || [NSCharacterSet.whitespaceAndNewlineCharacterSet characterIsMember:c]) {
            space = line.length > 0;
            continue;
        }
        if (space) [line appendString:@" "];
        space = NO;
        [line appendFormat:@"%C", c];
    }
    return line;
}

// The keys go out in small groups of letters, each as a "key" that carries those letters, so that every language and emoji work.
+ (void)postText:(NSString *)text {
    CGEventSourceRef source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState);
    NSMutableString *pending = [NSMutableString string];
    void (^flush)(void) = ^{
        NSUInteger count = pending.length;
        if (count == 0) return;
        UniChar letters[RelayKeyChunk];
        [pending getCharacters:letters range:NSMakeRange(0, count)];
        for (int pressed = 1; pressed >= 0; pressed--) {
            CGEventRef event = CGEventCreateKeyboardEvent(source, 0, pressed == 1);
            if (!event) continue;
            CGEventKeyboardSetUnicodeString(event, count, letters);
            CGEventSetFlags(event, 0);
            CGEventPost(kCGSessionEventTap, event);
            CFRelease(event);
        }
        [pending setString:@""];
        usleep(6000);
    };
    [text enumerateSubstringsInRange:NSMakeRange(0, text.length)
                             options:NSStringEnumerationByComposedCharacterSequences
                          usingBlock:^(NSString *piece, NSRange range, NSRange enclosing, BOOL *stop) {
        if (piece.length > RelayKeyChunk) return; // a strange run of marks: skipped rather than split
        if (pending.length + piece.length > RelayKeyChunk) flush();
        [pending appendString:piece];
    }];
    flush();
    if (source) CFRelease(source);
}

+ (void)typeText:(NSString *)text into:(NSRunningApplication *)target prepare:(dispatch_block_t)prepare done:(RelayActionDone)done {
    NSString *line = [self oneLine:text ?: @""];
    if (line.length == 0) {
        done(@"failed", @"");
        return;
    }
    if (![self accessAllowedAsking:YES]) { // the first time, macOS shows its own question
        done(@"access", @"");
        return;
    }
    if (!target || target.terminated) {
        done(@"gone", @"");
        return;
    }
    NSString *name = target.localizedName ?: @"";
    NSRunningApplication *front = NSWorkspace.sharedWorkspace.frontmostApplication;
    if (front && !RelayIsSelf(front) && front.processIdentifier != target.processIdentifier) {
        done(@"changed", front.localizedName ?: @""); // the person moved on: the words would land somewhere else
        return;
    }
    if (prepare) prepare();
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    [target activateWithOptions:NSApplicationActivateAllWindows];
#pragma clang diagnostic pop
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(RelayTypeDelay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        NSRunningApplication *now = NSWorkspace.sharedWorkspace.frontmostApplication;
        if (target.terminated) {
            done(@"gone", @"");
        } else if (now && !RelayIsSelf(now) && now.processIdentifier != target.processIdentifier) {
            done(@"changed", now.localizedName ?: @"");
        } else {
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
                [self postText:line];
                dispatch_async(dispatch_get_main_queue(), ^{ done(@"typed", name); });
            });
        }
    });
}

@end
