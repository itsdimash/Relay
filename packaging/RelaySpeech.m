#import "RelaySpeech.h"
#import <AVFoundation/AVFoundation.h>

// Answers are short by design (the page shortens them); this is only a ceiling against something absurd.
static const NSUInteger MaxSpokenCharacters = 700;

@interface RelaySpeech () <AVSpeechSynthesizerDelegate>
@property(nonatomic, strong) AVSpeechSynthesizer *synthesizer;
@property(nonatomic, strong, nullable) AVSpeechUtterance *current; // only this one's end counts: a replaced answer ends silently
@end

@implementation RelaySpeech

- (void)report:(NSString *)state {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.delegate speech:self reports:state];
    });
}

- (void)speak:(NSString *)text locale:(NSString *)localeIdentifier {
    if (![text isKindOfClass:NSString.class] || ![localeIdentifier isKindOfClass:NSString.class]) return;
    NSString *words = [text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!words.length) return;
    if (words.length > MaxSpokenCharacters) words = [words substringToIndex:MaxSpokenCharacters];
    AVSpeechSynthesisVoice *voice = [AVSpeechSynthesisVoice voiceWithLanguage:localeIdentifier];
    if (!voice) {
        [self stop];
        [self report:@"unavailable"]; // Russian text read by an English voice would be noise: say nothing
        return;
    }
    if (!self.synthesizer) {
        self.synthesizer = [[AVSpeechSynthesizer alloc] init];
        self.synthesizer.delegate = self;
    }
    AVSpeechUtterance *utterance = [AVSpeechUtterance speechUtteranceWithString:words];
    utterance.voice = voice;
    self.current = utterance; // set first, so the end of the answer being replaced is ignored
    if (self.synthesizer.speaking) [self.synthesizer stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    [self.synthesizer speakUtterance:utterance];
}

- (void)stop {
    self.current = nil;
    if (self.synthesizer.speaking) [self.synthesizer stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    [self report:@"end"];
}

#pragma mark - AVSpeechSynthesizerDelegate

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer didStartSpeechUtterance:(AVSpeechUtterance *)utterance {
    if (utterance == self.current) [self report:@"start"];
}

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer didFinishSpeechUtterance:(AVSpeechUtterance *)utterance {
    if (utterance != self.current) return;
    self.current = nil;
    [self report:@"end"];
}

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer didCancelSpeechUtterance:(AVSpeechUtterance *)utterance {
    if (utterance != self.current) return;
    self.current = nil;
    [self report:@"end"];
}

@end
