export type JobEvent = {
  id: string;
  sequence: number;
  stage: string;
  progress: number;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Job = {
  id: string;
  command: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  result_payload: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
};

export type MonitoredObject = {
  id: string;
  norad_id: string;
  name: string;
  active: boolean;
};

export type Trajectory = {
  norad_id: string;
  name: string;
  frame: string;
  points: Array<{
    timestamp: string;
    x_km: number;
    y_km: number;
    z_km: number;
    valid: boolean;
  }>;
};

export type RiskEvent = {
  id: string;
  tca: string;
  miss_distance_km: number;
  tier: string;
  probability_of_collision: number | null;
};
