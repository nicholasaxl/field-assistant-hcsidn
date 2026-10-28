import "@fontsource-variable/onest";
import "@fontsource-variable/unbounded";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./feedback.css";
import "./insights.css";
import "./conversation.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
