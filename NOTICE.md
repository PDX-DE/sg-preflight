## Internal Notice

`sg-preflight` is being developed as internal capability tooling for Paradox Cat GmbH Seriengrafik / 3D Car workflows.

See [LICENSE](LICENSE) for the governing internal proprietary license.

> [!WARNING]
> Mirrored SVN content, generated reports, screenshots, and workflow notes in this repo should be treated as internal company material by default.

- Treat repository contents, mirrored source data, screenshots, reports, and workflow notes as internal work material.
- Do not publish copied SVN content, BMW/SG assets, or project-specific outputs to public repositories.
- Keep generated evidence under `out/` and mirrored source trees such as `repositories/` untracked unless a deliberate internal release process says otherwise.
- When preparing internal milestones, prefer sanitized examples and avoid embedding confidential asset payloads directly into docs or issue discussions.
- Treat local UnleashedRecomp-derived resource folders as reference-only inputs unless a cleared internal distribution path exists for those assets.

## Third-Party Notice Stub

The native shell currently relies on the following third-party components. Keep this notice with any internal portable bundle or other packaged native-shell milestone.

| Component | Version | License | Upstream | Current use |
| --- | --- | --- | --- | --- |
| Dear ImGui | `v1.92.7-docking` | MIT | `https://github.com/ocornut/imgui` | Native shell UI runtime, Win32 backend, DX12 backend |
| nlohmann/json | `v3.12.0` | MIT | `https://github.com/nlohmann/json` | Backend bridge payload parsing and JSON transport |

### Packaging Rules

- Keep `LICENSE` and this `NOTICE.md` in any internal native-shell bundle.
- Do not treat local UnleashedRecomp resource folders as redistributable bundle inputs by default.
- Do not bundle mirrored `repositories/` or generated `out/` evidence unless there is a deliberate internal reason and a conscious opt-in.

This notice is intentionally lightweight until the final company-side repository policy is defined, but it is now explicit enough for internal alpha packaging.
