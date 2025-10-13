import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var hostText: String = ""
    @State private var pollingInterval: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("Base URL", text: $hostText)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .disableAutocorrection(true)

                    TextField("Polling interval (seconds)", text: $pollingInterval)
                        .keyboardType(.decimalPad)
                }

                Section("Automation") {
                    Toggle("Auto refresh status", isOn: $app.autoRefreshEnabled)
                    Stepper(value: $app.refreshIntervalSeconds, in: 1...30, step: 1) {
                        Text("Interval: \(app.refreshIntervalSeconds)s")
                    }
                }

                Section {
                    Button("Save") {
                        onSave()
                    }
                    .disabled(!canSave)

                    Button("Cancel", role: .cancel) {
                        dismiss()
                    }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
            .onAppear {
                hostText = app.baseURL
                pollingInterval = String(app.refreshIntervalSeconds)
            }
        }
    }

    private var canSave: Bool {
        !hostText.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func onSave() {
        app.baseURL = hostText.trimmingCharacters(in: .whitespaces)
        if let value = Double(pollingInterval), value >= 1 {
            app.refreshIntervalSeconds = Int(value)
        }
        dismiss()
    }
}

