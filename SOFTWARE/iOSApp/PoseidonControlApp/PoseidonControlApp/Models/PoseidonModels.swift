import Foundation

struct PoseidonStatus: Codable {
    let boards: [BoardStatus]
    let calibration: [String: Calibration]
    let syringes: [SyringeModel]
    let ack: [Int]

    var remainingSteps: [Int] {
        ack
    }
}

struct BoardStatus: Codable, Identifiable {
    let index: Int
    let port: String
    let baud: Int
    let is_open: Bool

    var id: Int { index }

    var isOpen: Bool { is_open }

    var label: String {
        index == 0 ? "Primary (P1/P2)" : "Expansion (P3/P4)"
    }

    var portSummary: String {
        port.isEmpty ? "Disconnected" : "\(port) @ \(baud)"
    }
}

struct Calibration: Codable {
    let steps_per_mm: Double
    let invert_dir: Bool

    var stepsPerMm: Double { steps_per_mm }
    var invertDir: Bool { invert_dir }
}

struct SyringeModel: Codable, Identifiable {
    let name: String
    let inner_d_mm: Double

    var id: String { name }
    var innerDiameter: Double { inner_d_mm }
}

struct PortListResponse: Codable {
    let ports: [String]
}

struct SyringeListResponse: Codable {
    let models: [SyringeModel]
}

enum SpeedUnit: String, CaseIterable, Identifiable {
    case mmPerSec = "mm/s"
    case mlPerSec = "mL/s"
    case mlPerMin = "mL/min"

    var id: String { rawValue }
    var title: String { rawValue }
}

enum AccelUnit: String, CaseIterable, Identifiable {
    case mmPerSec2 = "mm/s^2"
    case mlPerSec2 = "mL/s^2"

    var id: String { rawValue }
    var title: String { rawValue }
}

enum RunUnit: String, CaseIterable, Identifiable {
    case mm = "mm"
    case ml = "mL"
    case ul = "uL"

    var id: String { rawValue }
    var title: String { rawValue }
}
