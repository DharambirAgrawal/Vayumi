import { z } from "zod";

const settingsPatchSchema = z
  .record(z.string(), z.unknown())
  .refine((value) => Object.keys(value).length > 0, { message: "Provide at least one field to update" });

export const updateNotificationsSchema = settingsPatchSchema;
export const updatePrivacySchema = settingsPatchSchema;
export const updateAppearanceSchema = settingsPatchSchema;

export type SettingsPatchInput = z.infer<typeof settingsPatchSchema>;
