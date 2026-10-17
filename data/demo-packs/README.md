# Synthetic policy-pack demos

These are fictional internal buyer-policy examples. They are not legal frameworks, certifications or evidence about real organizations. The pack catalog guides extraction; only the uploaded applicable buyer policy supplies a requirement.

`demo_manifest.json` maps each registered pack to its review scope and three source PDFs. File paths are relative to the repository root. Every entry includes its SHA-256 and page count. `policy_pack_version` identifies the software's question set; `policy_version` identifies the uploaded buyer policy. They are separate concepts.

- **Data handling:** three original synthetic sources copied without modification. India-only backup policy and vendor claim versus a Singapore production replica. Supporting documents for other controls are deliberately absent.
- **Security assurance:** internal policy, questionnaire and operations register. All-MFA claim versus a recorded interactive privileged-account bypass. The separate security-test report is deliberately absent; a reference to it is not the report.
- **AI vendor review:** internal policy, questionnaire and operations register. Seven-day customer-content retention claim versus 45-day diagnostic-log retention. The subprocessor register is deliberately absent; absence is not proof that no subprocessors exist.

All documents have explicit October 2026 vendor/service/production scope and synthetic labels. Sources contain no expected model outcomes. Their three roles are not substitutes for document authenticity checks or real-world validation. The new two packs have offline contract, quote, scope and cache-boundary tests; no live-model result is claimed by creating these files.

Run `.venv/bin/python data/demo-packs/generate.py` to rebuild the manifest and PDFs. Generated PDFs may get new metadata hashes on rebuild; the manifest is regenerated with them. The default copied source hashes remain unchanged. `previews/` contains the visual inspection renders (13 pages total).
