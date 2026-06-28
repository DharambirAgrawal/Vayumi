import { z } from "zod";
import { appConfig } from "../../core/config/app.js";

const { settings: settingsLimits } = appConfig.limits;

const settingsPatchSchema = z
  .record(z.string(), z.unknown())
  .refine((value) => Object.keys(value).length > 0, { message: "Provide at least one field to update" })
  .refine((value) => Object.keys(value).length <= settingsLimits.maxKeys, {
    message: "Too many settings fields",
  })
  .refine((value) => JSON.stringify(value).length <= settingsLimits.maxSerializedBytes, {
    message: "Settings payload is too large",
  });

export const updateNotificationsSchema = settingsPatchSchema;
export const updatePrivacySchema = settingsPatchSchema;
export const updateAppearanceSchema = settingsPatchSchema;

export type SettingsPatchInput = z.infer<typeof settingsPatchSchema>;
