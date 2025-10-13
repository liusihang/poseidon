import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var app: AppViewModel
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            List {
                Section("Server") {
                    serverHeader
                }

                Section("Boards") {
                    if let status = app.status {
                        ForEach(status.boards) { board in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(board.label)
                                        .font(.headline)
                                    Text(board.portSummary)
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Circle()
                                    .fill(board.isOpen ? Color.green : Color.gray.opacity(0.4))
                                    .frame(width: 12, height: 12)
                            }
                        }
                    } else {
                        Text("No status available")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Global") {
                    Button("Refresh Status", action: app.refreshStatus)
                        .disabled(app.isBusy)
                    Button("Zero All", action: app.zeroAll)
                        .disabled(app.isBusy)
                    Button("Emergency Stop", action: app.estop)
                        .tint(.red)
                        .disabled(app.isBusy)
                    Button("Close Ports", action: app.closeAll)
                        .disabled(app.isBusy)
                }

                PumpSection()
                SyringeSection()
                LogSection()
            }
            .navigationTitle("Poseidon Control")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView().environmentObject(app)
            }
            .overlay(alignment: .bottom) {
                if let banner = app.banner {
                    BannerView(banner: banner) { app.dismissBanner() }
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .padding(.bottom, 16)
                }
            }
        }
        .onAppear {
            if app.status == nil {
                app.refreshStatus()
            }
        }
    }

    private var serverHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("Server URL (e.g. http://192.168.4.1:8000)", text: $app.baseURL)
                .textInputAutocapitalization(.never)
                .textContentType(.URL)
                .keyboardType(.URL)
                .disableAutocorrection(true)

            HStack {
                if app.isBusy {
                    ProgressView()
                }
                Spacer()
                Text(app.statusSummary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct PumpSection: View {
    @EnvironmentObject private var app: AppViewModel

    var body: some View {
        Section("Pumps") {
            if let status = app.status {
                ForEach(1...4, id: \.self) { pumpId in
                    NavigationLink {
                        PumpDetailView(pumpId: pumpId)
                    } label: {
                        PumpRow(pumpId: pumpId, remaining: status.remainingSteps[pumpId - 1])
                    }
                }
            } else {
                Text("Not connected")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct PumpRow: View {
    let pumpId: Int
    let remaining: Int?

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text("Pump \(pumpId)")
                    .font(.headline)
                if let remaining {
                    Text("Remaining steps: \(remaining)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    Text("No data")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            Image(systemName: "chevron.right")
                .foregroundStyle(.tertiary)
        }
    }
}

private struct SyringeSection: View {
    @EnvironmentObject private var app: AppViewModel

    var body: some View {
        Section("Syringes") {
            if app.syringes.isEmpty {
                Button("Fetch Syringes", action: app.refreshSyringes)
            } else {
                ForEach(app.syringes) { model in
                    VStack(alignment: .leading) {
                        Text(model.name)
                        Text("Dia \(String(format: "%.3f", model.innerDiameter)) mm")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                Button("Push Syringe List", action: app.pushSyringes)
            }
        }
    }
}

private struct LogSection: View {
    @EnvironmentObject private var app: AppViewModel

    var body: some View {
        if !app.logs.isEmpty {
            Section("Logs") {
                ForEach(app.logs, id: \.self) { line in
                    Text(line)
                        .font(.system(.footnote, design: .monospaced))
                }
                Button("Clear Logs", action: app.clearLogs)
            }
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .environmentObject(AppViewModel.mock())
    }
}
