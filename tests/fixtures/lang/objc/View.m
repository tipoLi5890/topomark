// A view controller.
#import "View.h"

@interface ViewController () {
    int _count;
}
@property (nonatomic, strong) NSString *title;
- (void)reload;
@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    NSString *s = @"brace { here";
}

- (NSInteger)add:(NSInteger)a to:(NSInteger)b {
    return a + b;
}

+ (instancetype)shared {
    return nil;
}

@end
