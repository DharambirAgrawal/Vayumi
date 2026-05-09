export type CronJobDefinition = {
  name: string;
  schedule: string;
  run: () => Promise<void>;
};
