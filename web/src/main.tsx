import { ErrorBoundary } from "solid-js";
import { render } from "solid-js/web";
import App from "./App";
import { t } from "./i18n/zh";
import "./styles/app.css";

document.title = `${t.appName} — ${t.tagline}`;

render(
    () => (
        <ErrorBoundary
            fallback={(err) => (
                <main class="reader-fatal">
                    <p>{err instanceof Error ? err.message : String(err)}</p>
                    <a class="btn-ghost" href="#/">
                        ← {t.reader.back}
                    </a>
                </main>
            )}
        >
            <App />
        </ErrorBoundary>
    ),
    document.getElementById("app")!,
);
