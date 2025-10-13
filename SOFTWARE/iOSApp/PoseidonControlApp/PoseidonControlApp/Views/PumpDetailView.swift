import SwiftUI

struct PumpDetailView: View {
    @EnvironmentObject private var app: AppViewModel

    let pumpId: Int

    @State private var speedValue = "0.50"
    @State private var speedUnit: SpeedUnit = .mlPerMin
    @State private var accelValue = "5.0"
    @State private var accelUnit: AccelUnit = .mlPerSec2
    @State private var runValue = "1.0"
    @State private var runUnit: RunUnit = .ml
    @State private var jogValue = "0.1"
    @State private var jogUnit: RunUnit = .ml
    @State private var stepsValue = "800.0"
    @State private var planMm = "10.0"
    @State private var measMm = "10.0"
    @State private var planMl = "1.0"
    @State private var measMl = "1.0"
    @State private var selectedSyringe = ""

    var body: some View {
        Form {
            statusSection
            motionSection
            runSection
            calibrationSection
        }
        .navigationTitle("Pump \(pumpId)")
        .onAppear {
            if selectedSyringe.isEmpty {
                selectedSyringe = app.syringes.first?.name ?? ""
            }
            if let cal = app.calibration[pumpId] {
                stepsValue = String(format: "%.3f", cal.stepsPerMm)
            }
        }
    }

    private var statusSection: some View {
        Section("Status") {
            if let cal = app.calibration[pumpId] {
                Toggle(
                    "Invert direction",
                    isOn: Binding(
                        get: { cal.invertDir },
                        set: { value in
                            Task { await app.setInvert(pumpId: pumpId, invert: value) }
                        }
                    )
                )
                Text("steps/mm: \(String(format: "%.3f", cal.stepsPerMm))")
                if let remaining = app.status?.remainingSteps[pumpId - 1] {
                    Text("Remaining steps: \(remaining)")
                }
            } else {
                Text("No calibration data")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var motionSection: some View {
        Section("Speed / Accel") {
            HStack {
                TextField("Speed", text: $speedValue)
                    .keyboardType(.decimalPad)
                Picker("Unit", selection: $speedUnit) {
                    ForEach(SpeedUnit.allCases) { unit in
                        Text(unit.title).tag(unit)
                    }
                }
                .pickerStyle(.menu)
            }
            Button("Apply speed") {
                Task { await app.setSpeed(pumpId: pumpId, value: speedValue, unit: speedUnit) }
            }

            HStack {
                TextField("Acceleration", text: $accelValue)
                    .keyboardType(.decimalPad)
                Picker("Unit", selection: $accelUnit) {
                    ForEach(AccelUnit.allCases) { unit in
                        Text(unit.title).tag(unit)
                    }
                }
                .pickerStyle(.menu)
            }
            Button("Apply accel") {
                Task { await app.setAccel(pumpId: pumpId, value: accelValue, unit: accelUnit) }
            }
        }
    }

    private var runSection: some View {
        Section("Run / Jog") {
            HStack {
                TextField("Value", text: $runValue)
                    .keyboardType(.decimalPad)
                Picker("Unit", selection: $runUnit) {
                    ForEach(RunUnit.allCases) { unit in
                        Text(unit.title).tag(unit)
                    }
                }
                .pickerStyle(.menu)
            }
            Button("Run") {
                Task { await app.run(pumpId: pumpId, value: runValue, unit: runUnit) }
            }

            HStack {
                TextField("Jog delta", text: $jogValue)
                    .keyboardType(.decimalPad)
                Picker("Unit", selection: $jogUnit) {
                    ForEach(RunUnit.allCases) { unit in
                        Text(unit.title).tag(unit)
                    }
                }
                .pickerStyle(.menu)
            }
            HStack {
                Button("Jog -") {
                    Task { await app.jog(pumpId: pumpId, delta: "-" + jogValue, unit: jogUnit) }
                }
                Button("Jog +") {
                    Task { await app.jog(pumpId: pumpId, delta: jogValue, unit: jogUnit) }
                }
            }

            HStack {
                Button("Pause") { Task { await app.pause(pumpId: pumpId) } }
                Button("Stop", role: .destructive) { Task { await app.stop(pumpId: pumpId) } }
                Button("Resume") { Task { await app.resume(pumpId: pumpId) } }
            }
        }
    }

    private var calibrationSection: some View {
        Section("Calibration") {
            TextField("steps/mm", text: $stepsValue)
                .keyboardType(.decimalPad)
            Button("Save steps/mm") {
                Task { await app.setStepsPerMM(pumpId: pumpId, value: stepsValue) }
            }

            Group {
                Text("Travel calibration")
                    .font(.headline)
                TextField("Planned distance (mm)", text: $planMm)
                    .keyboardType(.decimalPad)
                TextField("Measured distance (mm)", text: $measMm)
                    .keyboardType(.decimalPad)
                Button("Apply travel correction") {
                    Task { await app.applyTravel(pumpId: pumpId, plan: planMm, meas: measMm) }
                }
            }

            if !app.syringes.isEmpty {
                Group {
                    Text("Volume calibration")
                        .font(.headline)
                    TextField("Target volume (mL)", text: $planMl)
                        .keyboardType(.decimalPad)
                    TextField("Measured volume (mL)", text: $measMl)
                        .keyboardType(.decimalPad)
                    Picker("Syringe", selection: $selectedSyringe) {
                        ForEach(app.syringes) { model in
                            Text(model.name).tag(model.name)
                        }
                    }
                    .pickerStyle(.navigationLink)
                    Button("Apply volume correction") {
                        Task {
                            await app.applyVolume(
                                pumpId: pumpId,
                                target: planMl,
                                meas: measMl,
                                syringe: selectedSyringe
                            )
                        }
                    }
                }
            }
        }
    }
}

struct PumpDetailView_Previews: PreviewProvider {
    static var previews: some View {
        NavigationStack {
            PumpDetailView(pumpId: 1)
                .environmentObject(AppViewModel.mock())
        }
    }
}

