import {auth} from '../home/auth';

/** Freeze the owner and navigation admission, including leave/re-entry epochs. */
export function workspaceDeletionContext(context: {userId:string; workspaceId:string}) {
  const user = context.userId, workspace = context.workspaceId;
  const owner = auth.me?.id, generation = auth.sessionGeneration, epoch = auth.requestEpoch;
  return () => !auth.suspended && !auth.sessionClosing && owner === auth.me?.id &&
    generation === auth.sessionGeneration && epoch === auth.requestEpoch &&
    user === context.userId && workspace === context.workspaceId;
}
