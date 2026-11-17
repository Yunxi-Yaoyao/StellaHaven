import { Container } from 'pixi.js';
import type { Live2DModel, Live2DFactoryOptions, Live2DModelOptions } from 'pixi-live2d-display/cubism4';
import type { createLive2dLifetime } from './live2dLifetime';

/** Own the constructor result even when 0.4.0's from() rejects after allocating a core. */
export async function loadOwnedLive2dModel(
  Model: typeof Live2DModel,
  source: string,
  options: Live2DFactoryOptions,
  lifetime: ReturnType<typeof createLive2dLifetime>,
) {
  let owned: Live2DModel | undefined;
  // from() constructs `new this(options)`. A local subclass captures only this load;
  // no shared factory/prototype mutation, callbacks, or second setup invocation.
  class OwnedModel extends Model {
    constructor(options?: Live2DModelOptions) {
      super(options);
      owned = this;
    }
  }
  try {
    return await OwnedModel.from(source, options);
  } finally {
    const model = owned;
    if (model) lifetime.defer(() => {
      if (model.destroyed) return;
      // Wait for factory settlement: destroying mid-setup lets its continuations
      // write into a dead internal model. A disposed lifetime releases here too.
      // Never destroy URL-cached textures: another owner may already use them.
      if (model.internalModel) model.destroy();
      else {
        // 0.4.0 destroy() unconditionally dereferences internalModel. Before
        // modelLoaded there are only a Container and loader destroy listeners.
        model.emit('destroy');
        Container.prototype.destroy.call(model);
      }
    });
  }
}
