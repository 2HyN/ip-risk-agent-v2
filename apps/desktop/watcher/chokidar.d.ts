/**
 * chokidar 5.0.0은 실제로 index.d.ts를 포함하지만, package.json의 "exports"
 * map에 "types" 조건이 선언돼 있지 않아 TypeScript의 "moduleResolution":
 * "NodeNext" 하에서는 타입 선언을 찾지 못한다 (실제 검증함, 업스트림 패키징
 * 누락으로 보임). 우리가 실제로 쓰는 최소 표면(watch/on/once/close)만
 * ambient module로 직접 선언해서 우회한다.
 */

declare module "chokidar" {
  export interface FSWatcher {
    on(event: string, listener: (...args: any[]) => void): this;
    once(event: string, listener: (...args: any[]) => void): this;
    close(): Promise<void>;
  }

  export interface WatchOptions {
    ignoreInitial?: boolean;
    [key: string]: unknown;
  }

  export function watch(paths: string | string[], options?: WatchOptions): FSWatcher;

  const chokidar: {
    watch: typeof watch;
  };
  export default chokidar;
}
