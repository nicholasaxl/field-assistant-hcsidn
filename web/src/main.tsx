import "@fontsource-variable/onest";
import "@fontsource-variable/unbounded";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./feedback.css";
import "./insights.css";
import "./conversation.css";
import "./models.css";
import "./density.css"; // keep last: it overrides the larger defaults above

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
