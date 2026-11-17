import {it,expect,vi} from 'vitest';
import {watchNavRevision} from './realtime';

it('reconnects with bounded delay, rejects stale sockets and stops on auth denial',()=>{
 vi.useFakeTimers();
 const sockets:any[]=[];const make=()=>{const socket:any={close:vi.fn()};sockets.push(socket);return socket;};
 const hints=vi.fn(),status=vi.fn();const stop=watchNavRevision(make as any,hints,status);
 sockets[0].onmessage({data:'{"type":"nav_revision","revision":4}'});expect(hints).toHaveBeenCalledWith(4);
 for(const data of ['{}','{"type":"nav_revision","revision":-1}','{"type":"nav_revision","revision":1.5}'])sockets[0].onmessage({data});
 expect(hints).toHaveBeenCalledTimes(1);
 sockets[0].onclose({code:1006});vi.advanceTimersByTime(2000);expect(sockets).toHaveLength(2);
 sockets[0].onmessage({data:'{"type":"nav_revision","revision":99}'});expect(hints).toHaveBeenCalledTimes(1);
 sockets[1].onclose({code:1008});vi.advanceTimersByTime(60000);expect(sockets).toHaveLength(2);
 stop();sockets[1].onmessage({data:'{"type":"nav_revision","revision":100}'});expect(hints).toHaveBeenCalledTimes(1);vi.useRealTimers();
});
