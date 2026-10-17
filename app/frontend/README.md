# EvidenceDesk frontend

React / TypeScript / Vite interface. The UI uses the real API contract in `docs/API_CONTRACT.md`; it does not generate or hardcode sample findings.

```sh
npm install
npm run dev
npm run build
```

Vite forwards `/api` to `http://127.0.0.1:8080`. Production assets are written to `dist/`; serve them on the same origin as the API. Deep links use `?review=sample` or `?review=<id>`.

`GET /api/session` initializes the local HttpOnly session cookie. In Firebase mode the API returns `auth_mode: "firebase"` and `firebase_config`; the frontend creates/resumes an anonymous authenticated account and attaches its ID token to API calls. Optionally, `VITE_FIREBASE_CONFIG` can contain the same Firebase public configuration JSON at build time. PDF and export requests use authenticated fetch and Blob URLs.

Reviewer follow-up drafts are persisted inside the decision note under the `Follow-up draft:` marker because the v1 decision endpoint accepts only `decision` and `note`. The UI separates this marker back into an editable draft on reload. Copy does not send a message. Uploaded documents and analysis data are handled by the backend.

Fonts request DM Sans / Manrope from Google Fonts, with system fallbacks. The layout and workflow remain functional without network font access.
