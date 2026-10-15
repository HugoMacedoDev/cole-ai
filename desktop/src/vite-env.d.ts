/// <reference types="vite/client" />

interface Window {
  cola?: {
    desktop: {
      setAlwaysOnTop(enabled: boolean): Promise<void>;
      quit(): Promise<void>;
    };
  };
}
