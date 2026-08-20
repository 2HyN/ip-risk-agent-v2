/**
 * ESM 기반 test/renderer가 CommonJS preload와 동일한 capability 계약을
 * 사용하도록 하는 얇은 re-export다.
 */
export {
  ALLOWED_RENDERER_CHANNELS,
  FORBIDDEN_RENDERER_CHANNELS,
  type AllowedRendererChannel,
} from "./channels.cjs";
