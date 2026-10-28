import { motion } from "motion/react";
import { Alert as AlertIcon } from "./Icons";
import type { Alert } from "./types";

/** Safety alerts come from rules in data/policies.json, never from the model. */
export function Alerts({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) return null;
  const critical = alerts.some((a) => a.level === "critical");
  return (
    <div className="alerts" role={critical ? "alert" : "status"}>
      {alerts.map((alert, i) => (
        <motion.div
          key={alert.id}
          className="alert"
          data-level={alert.level}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: i * 0.08, ease: [0.22, 1, 0.36, 1] }}
        >
          <AlertIcon />
          <div>
            <p className="alert-title">{alert.title}</p>
            <p className="alert-message">{alert.message}</p>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
