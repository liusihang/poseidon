import SwiftUI

struct BannerData: Identifiable {
    enum Kind {
        case info
        case success
        case error

        var color: Color {
            switch self {
            case .info: return .blue
            case .success: return .green
            case .error: return .red
            }
        }
    }

    let id = UUID()
    let kind: Kind
    let message: String
}

struct BannerView: View {
    let banner: BannerData
    var onDismiss: (() -> Void)?

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: iconName)
                .font(.headline)
            Text(banner.message)
                .font(.subheadline)
            Spacer()
            Button {
                onDismiss?()
            } label: {
                Image(systemName: "xmark")
                    .font(.subheadline)
            }
            .buttonStyle(.plain)
        }
        .padding()
        .background(.regularMaterial)
        .overlay(
            RoundedRectangle(cornerRadius: 12).stroke(banner.kind.color.opacity(0.6), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 24)
        .shadow(color: .black.opacity(0.2), radius: 8, x: 0, y: 3)
    }

    private var iconName: String {
        switch banner.kind {
        case .info: return "info.circle"
        case .success: return "checkmark.circle"
        case .error: return "exclamationmark.triangle"
        }
    }
}

