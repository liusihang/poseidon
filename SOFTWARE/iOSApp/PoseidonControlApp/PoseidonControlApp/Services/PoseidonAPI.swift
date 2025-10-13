import Foundation

actor PoseidonAPI {
    private var baseURL: URL
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL) {
        self.baseURL = baseURL
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    func updateBaseURL(_ url: URL) {
        self.baseURL = url
    }

    // MARK: - Public API

    func fetchStatus() async throws -> PoseidonStatus {
        try await get(path: "/api/status", as: PoseidonStatus.self)
    }

    func listPorts() async throws -> [String] {
        try await get(path: "/api/ports", as: PortListResponse.self).ports
    }

    func openBoard(index: Int, port: String, baud: Int) async throws {
        struct Payload: Encodable {
            let board_index: Int
            let port: String
            let baud: Int
        }
        try await post(path: "/api/boards/open", body: Payload(board_index: index, port: port, baud: baud))
    }

    func closeAll() async throws {
        try await post(path: "/api/boards/close-all")
    }

    func zeroAll() async throws {
        try await post(path: "/api/boards/zero")
    }

    func estop() async throws {
        try await post(path: "/api/boards/estop")
    }

    func setSpeed(pumpId: Int, value: Double, unit: SpeedUnit) async throws {
        struct Payload: Encodable {
            let value: Double
            let unit: String
        }
        try await post(path: "/api/pumps/\(pumpId)/speed", body: Payload(value: value, unit: unit.rawValue))
    }

    func setAccel(pumpId: Int, value: Double, unit: AccelUnit) async throws {
        struct Payload: Encodable {
            let value: Double
            let unit: String
        }
        try await post(path: "/api/pumps/\(pumpId)/accel", body: Payload(value: value, unit: unit.rawValue))
    }

    func run(pumpId: Int, value: Double, unit: RunUnit) async throws {
        struct Payload: Encodable {
            let value: Double
            let unit: String
        }
        try await post(path: "/api/pumps/\(pumpId)/run", body: Payload(value: value, unit: unit.rawValue))
    }

    func jog(pumpId: Int, delta: Double, unit: RunUnit) async throws {
        struct Payload: Encodable {
            let delta: Double
            let unit: String
        }
        try await post(path: "/api/pumps/\(pumpId)/jog", body: Payload(delta: delta, unit: unit.rawValue))
    }

    func pause(pumpId: Int) async throws {
        try await post(path: "/api/pumps/\(pumpId)/pause")
    }

    func stop(pumpId: Int) async throws {
        try await post(path: "/api/pumps/\(pumpId)/stop")
    }

    func resume(pumpId: Int) async throws {
        try await post(path: "/api/pumps/\(pumpId)/resume")
    }

    func setStepsPerMM(pumpId: Int, value: Double) async throws {
        struct Payload: Encodable { let steps_per_mm: Double }
        try await post(path: "/api/calibration/\(pumpId)/steps", body: Payload(steps_per_mm: value))
    }

    func setInvert(pumpId: Int, invert: Bool) async throws {
        struct Payload: Encodable { let invert: Bool }
        try await post(path: "/api/calibration/\(pumpId)/invert", body: Payload(invert: invert))
    }

    func applyTravelCalibration(pumpId: Int, plan: Double, meas: Double) async throws -> Double {
        struct Payload: Encodable {
            let plan_mm: Double
            let meas_mm: Double
        }
        struct Response: Decodable { let steps_per_mm: Double }
        return try await post(path: "/api/calibration/\(pumpId)/travel", body: Payload(plan_mm: plan, meas_mm: meas)).steps_per_mm
    }

    func applyVolumeCalibration(pumpId: Int, target: Double, meas: Double, syringe: String) async throws -> Double {
        struct Payload: Encodable {
            let target_ml: Double
            let meas_ml: Double
            let syringe_name: String
        }
        struct Response: Decodable { let steps_per_mm: Double }
        return try await post(
            path: "/api/calibration/\(pumpId)/volume",
            body: Payload(target_ml: target, meas_ml: meas, syringe_name: syringe)
        ).steps_per_mm
    }

    func fetchSyringes() async throws -> [SyringeModel] {
        try await get(path: "/api/syringes", as: SyringeListResponse.self).models
    }

    func pushSyringes(_ models: [SyringeModel]) async throws {
        struct Payload: Encodable {
            let models: [Model]
            struct Model: Encodable {
                let name: String
                let inner_d_mm: Double
            }
        }
        let payload = Payload(models: models.map { .init(name: $0.name, inner_d_mm: $0.innerDiameter) })
        try await put(path: "/api/syringes", body: payload)
    }

    // MARK: - Helpers

    private func get<T: Decodable>(path: String, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: URLRequest(url: url(for: path)))
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func post<T: Encodable, U: Decodable>(path: String, body: T? = nil) async throws -> U {
        var request = URLRequest(url: url(for: path))
        request.httpMethod = "POST"
        if let body {
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        if U.self == EmptyResponse.self {
            return EmptyResponse() as! U
        }
        return try decoder.decode(U.self, from: data.isEmpty ? Data("{}".utf8) : data)
    }

    @discardableResult
    private func post(path: String) async throws {
        let _: EmptyResponse = try await post(path: path, body: Optional<Empty>.none)
    }

    private func put<T: Encodable>(path: String, body: T) async throws {
        var request = URLRequest(url: url(for: path))
        request.httpMethod = "PUT"
        request.httpBody = try encoder.encode(body)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (_, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: nil)
    }

    private func url(for path: String) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) ?? URLComponents()
        components.path = path
        return components.url ?? baseURL.appendingPathComponent(path)
    }

    private func validate(response: URLResponse, data: Data?) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            let message: String
            if let data, let body = String(data: data, encoding: .utf8), !body.isEmpty {
                message = body
            } else {
                message = HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            }
            throw PoseidonAPIError.server(message)
        }
    }
}

private struct Empty: Encodable {}
private struct EmptyResponse: Decodable {}

enum PoseidonAPIError: Error, LocalizedError {
    case invalidBaseURL
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: return "Invalid server URL."
        case .server(let message): return message
        }
    }
}
