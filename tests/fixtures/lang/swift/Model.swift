// Model types for the app.
import Foundation

/// A user.
public struct User: Codable {
    public let id: Int
    private(set) var name: String
    fileprivate var cache = [String: Int]()

    public init(id: Int, name: String) {
        self.id = id
        self.name = name
    }

    var greeting: String {
        "Hello \(name.isEmpty ? "{anon}" : "\(name)")"
    }

    /* outer /* nested { */ still comment */
    func rename(_ to: String) -> User {
        var u = self
        u.name = to
        return u
    }
}

enum Direction {
    case north, south
    case east(Int)

    func flipped() -> Direction {
        switch self {
        case .north: return .south
        default: return self
        }
    }
}

protocol Store {
    associatedtype Item
    func load() -> [Item]
    var count: Int { get }
}

extension User: Equatable {
    public static func == (a: User, b: User) -> Bool { a.id == b.id }
}

#if os(iOS)
class Platform {}
#else
class Platform {
    let s = """
    multi { line
    """
}
#endif

private func helper() {}
