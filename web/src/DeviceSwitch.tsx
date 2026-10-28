import { motion } from "motion/react";
import { DeviceIcon } from "./Icons";
import { deviceKind, deviceLabel } from "./utils";

type Props = { devices: string[]; value: string; onChange: (device: string) => void };

export function DeviceSwitch({ devices, value, onChange }: Props) {
  const options = ["all", ...devices];
  return (
    <div className="device-switch" role="radiogroup" aria-label="Device model">
      {options.map((option) => {
        const checked = option === value;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={checked}
            className="device-opt"
            onClick={() => onChange(option)}
          >
            {checked && (
              <motion.span
                layoutId="device-pill"
                className="device-pill"
                transition={{ type: "spring", stiffness: 520, damping: 38 }}
              />
            )}
            <DeviceIcon kind={deviceKind(option)} />
            <span>{deviceLabel(option)}</span>
          </button>
        );
      })}
    </div>
  );
}
