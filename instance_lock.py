"""OS-owned single-writer lease. Released automatically on process exit/crash."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self,root):
        root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
        self.file=(root/'.novel-instance.lock').open('a+b')
        try:
            if self.file.seek(0,2)==0:self.file.write(b'1');self.file.flush()
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise ValueError('Cette bibliothèque est déjà ouverte dans Novel. Utiliser la fenêtre existante ou fermer cette instance avant de relancer.') from error

    def close(self):
        if self.file.closed:return
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
        self.file.close()
