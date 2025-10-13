import Foundation
import SwiftUI

@MainActor
final class AppViewModel: ObservableObject {
    @Published var baseURL: String = "http://192.168.4.1:8000" {
        didSet { configureAPI() }
    }

    @Published private(set) var status: PoseidonStatus?
    @Published private(set) var syringes: [SyringeModel] = []
    @Published private(set) var calibration: [Int: Calibration] = [:]
    @Published private(set) var isBusy = false
    @Published private(set) var banner: BannerData?
    @Published private(set) var logs: [String] = []

    @Published var autoRefreshEnabled = true
    @Published var refreshIntervalSeconds: Int = 3 {
        didSet { restartTimer() }
    }

    private var api: PoseidonAPI?
    private var timer: Timer?

    init() {
        configureAPI()
        restartTimer()
    }

    deinit {
        timer?.invalidate()
    }

    private func configureAPI() {
        guard let url = URL(string: baseURL) else {
            banner = BannerData(kind: .error, message: "Invalid server URL.")
            return
        }
        if let api {
            Task.detached { await api.updateBaseURL(url) }
        } else {
            api = PoseidonAPI(baseURL: url)
        }
    }

    private func restartTimer() {
        timer?.invalidate()
        guard autoRefreshEnabled else { return }
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(refreshIntervalSeconds), repeats: true) { [weak self] _ in
            Task { await self?.refreshStatus() }
        }
    }

    func refreshStatus() {
        Task {
            await perform("refresh status") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                let snapshot = try await api.fetchStatus()
                status = snapshot
                calibration = snapshot.calibration.reduce(into: [:]) { dict, entry in
                    if let id = Int(entry.key) {
                        dict[id] = entry.value
                    }
                }
                syringes = snapshot.syringes
            }
        }
    }

    func refreshSyringes() {
        Task {
            await perform("refresh syringes") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                syringes = try await api.fetchSyringes()
            }
        }
    }

    func pushSyringes() {
        Task {
            await perform("sync syringes") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                try await api.pushSyringes(syringes)
            }
        }
    }

    func setSpeed(pumpId: Int, value: String, unit: SpeedUnit) async {
        await perform("set speed") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let measured = try ValueParser.double(value)
            try await api.setSpeed(pumpId: pumpId, value: measured, unit: unit)
        }
    }

    func setAccel(pumpId: Int, value: String, unit: AccelUnit) async {
        await perform("set acceleration") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let measured = try ValueParser.double(value)
            try await api.setAccel(pumpId: pumpId, value: measured, unit: unit)
        }
    }

    func run(pumpId: Int, value: String, unit: RunUnit) async {
        await perform("run pump") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let measured = try ValueParser.double(value)
            try await api.run(pumpId: pumpId, value: measured, unit: unit)
        }
    }

    func jog(pumpId: Int, delta: String, unit: RunUnit) async {
        await perform("jog pump") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let measured = try ValueParser.double(delta)
            try await api.jog(pumpId: pumpId, delta: measured, unit: unit)
        }
    }

    func pause(pumpId: Int) async {
        await perform("pause pump") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            try await api.pause(pumpId: pumpId)
        }
    }

    func stop(pumpId: Int) async {
        await perform("stop pump") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            try await api.stop(pumpId: pumpId)
        }
    }

    func resume(pumpId: Int) async {
        await perform("resume pump") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            try await api.resume(pumpId: pumpId)
        }
    }

    func setStepsPerMM(pumpId: Int, value: String) async {
        await perform("save steps/mm") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let measured = try ValueParser.double(value)
            try await api.setStepsPerMM(pumpId: pumpId, value: measured)
            await refreshStatus()
        }
    }

    func setInvert(pumpId: Int, invert: Bool) async {
        await perform("toggle invert") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            try await api.setInvert(pumpId: pumpId, invert: invert)
            await refreshStatus()
        }
    }

    func applyTravel(pumpId: Int, plan: String, meas: String) async {
        await perform("travel calibration") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let planValue = try ValueParser.double(plan)
            let measValue = try ValueParser.double(meas)
            let result = try await api.applyTravelCalibration(pumpId: pumpId, plan: planValue, meas: measValue)
            banner = BannerData(kind: .success, message: "New steps/mm: \(String(format: "%.3f", result))")
            await refreshStatus()
        }
    }

    func applyVolume(pumpId: Int, target: String, meas: String, syringe: String) async {
        await perform("volume calibration") {
            guard let api else { throw PoseidonAPIError.invalidBaseURL }
            let targetValue = try ValueParser.double(target)
            let measValue = try ValueParser.double(meas)
            let result = try await api.applyVolumeCalibration(
                pumpId: pumpId,
                target: targetValue,
                meas: measValue,
                syringe: syringe
            )
            banner = BannerData(kind: .success, message: "New steps/mm: \(String(format: "%.3f", result))")
            await refreshStatus()
        }
    }

    func zeroAll() {
        Task {
            await perform("zero all") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                try await api.zeroAll()
            }
        }
    }

    func estop() {
        Task {
            await perform("emergency stop") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                try await api.estop()
            }
        }
    }

    func closeAll() {
        Task {
            await perform("close serial") {
                guard let api else { throw PoseidonAPIError.invalidBaseURL }
                try await api.closeAll()
                await refreshStatus()
            }
        }
    }

    func dismissBanner() {
        banner = nil
    }

    func clearLogs() {
        logs.removeAll()
    }

    var statusSummary: String {
        if isBusy {
            return "Syncing..."
        } else if let status {
            let openCount = status.boards.filter(\.isOpen).count
            return "Boards online \(openCount)/\(status.boards.count)"
        } else {
            return "Not connected"
        }
    }

    private func perform(
        _ title: String,
        operation: @escaping @Sendable () async throws -> Void
    ) async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation()
            log("[OK] \(title)")
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            log("[ERR] \(title): \(message)")
            banner = BannerData(kind: .error, message: message)
        }
    }

    private func log(_ message: String) {
        logs.append(message)
        if logs.count > 200 {
            logs.removeFirst()
        }
    }

    static func mock() -> AppViewModel {
        let vm = AppViewModel()
        vm.status = PoseidonStatus(
            boards: [
                BoardStatus(index: 0, port: "ttyUSB0", baud: 230400, is_open: true),
                BoardStatus(index: 1, port: "", baud: 230400, is_open: false),
            ],
            calibration: [
                "1": Calibration(steps_per_mm: 800, invert_dir: false),
                "2": Calibration(steps_per_mm: 810, invert_dir: false),
                "3": Calibration(steps_per_mm: 820, invert_dir: true),
                "4": Calibration(steps_per_mm: 790, invert_dir: false),
            ],
            syringes: [
                SyringeModel(name: "BD 1 mL", inner_d_mm: 4.699),
                SyringeModel(name: "10 mL", inner_d_mm: 14.5),
            ],
            ack: [1200, 0, 40, 0]
        )
        vm.calibration = [
            1: Calibration(steps_per_mm: 800, invert_dir: false),
            2: Calibration(steps_per_mm: 810, invert_dir: false),
            3: Calibration(steps_per_mm: 820, invert_dir: true),
            4: Calibration(steps_per_mm: 790, invert_dir: false),
        ]
        vm.syringes = vm.status?.syringes ?? []
        vm.logs = ["[OK] Mock data ready"]
        return vm
    }
}

