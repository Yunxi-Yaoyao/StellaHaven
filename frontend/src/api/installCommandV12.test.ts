import {expect,test,vi,beforeEach} from 'vitest';
vi.mock('./client',()=>({api:vi.fn()}));
import {api} from './client';
import * as servers from './servers';
beforeEach(()=>vi.resetAllMocks());
test('command capability is explicit POST no-store and validates credential',async()=>{vi.mocked(api).mockResolvedValue({url:'https://applied.example',token:'fixture-secret',command:'backend command fixture-secret'});const signal=new AbortController().signal;const get=(servers as any).getInstallCommand;expect(typeof get).toBe('function');await expect(get(7,signal)).resolves.toMatchObject({command:'backend command fixture-secret'});expect(api).toHaveBeenCalledWith('/nodes/7/install-command',{method:'POST',cache:'no-store',signal});});
test('valid origin labels are not mistaken for missing credentials',async()=>{vi.mocked(api).mockResolvedValue({url:'https://null.example',token:'fixture-secret',command:'curl https://null.example/agent/install.sh --token fixture-secret'});await expect(servers.getInstallCommand(7)).resolves.toMatchObject({url:'https://null.example'});});
test.each(['',null,undefined,'undefined','null'])('empty or sentinel credential %s is never renderable',async token=>{vi.mocked(api).mockResolvedValue({url:'https://applied.example',token,command:'backend command'});const get=(servers as any).getInstallCommand;expect(typeof get).toBe('function');await expect(get(7)).rejects.toThrow('安装命令响应无效');});
