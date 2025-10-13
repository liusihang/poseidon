import Foundation

enum ValueParser {
    static func double(_ text: String) throws -> Double {
        guard let value = Double(text.trimmingCharacters(in: .whitespaces)) else {
            throw PoseidonAPIError.server("Invalid number: \(text)")
        }
        return value
    }
}
