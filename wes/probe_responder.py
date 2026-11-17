"""Answer node probes on the FL port while no run is active. Sandbox only.

The FL server starts per run, so the FL port of an idle hub would refuse
connections, and the node probe (`tests/probe_submit.py`) couldn't tell a node
that may reach the hub from one behind a firewall that rejects connections.
This responder speaks the protocol of `tests/probe.py listen`: it accepts a
connection and closes it at once, nothing else. The WES starts it at startup
and after each run, and stops it before the FL server of a run starts.

Standard library only, so that its unit tests run without the image.
"""

import errno
import logging
import selectors
import socket
import threading

logger = logging.getLogger("wes")

ON = {"1", "true", "yes", "on"}
OFF = {"0", "false", "no", "off"}


def responder_enabled(value: str | None) -> bool:
    """Read the setting `FL_PROBE_RESPONDER`.

    Args:
        value: Its value, or `None` if it isn't set.

    Returns:
        Whether the responder runs: by default, yes. An empty value counts as
        unset, as Compose's `${FL_PROBE_RESPONDER:-1}` reads it.

    Raises:
        ValueError: The value is neither on nor off, so that a typo doesn't pick a side.
    """
    word = (value or "").strip().lower()
    if not word or word in ON:
        return True
    if word in OFF:
        return False
    raise ValueError(f"FL_PROBE_RESPONDER must be one of {sorted(ON)} or {sorted(OFF)}, not {value!r}")


class ProbeResponder:
    """Accept connections on a port and close them, in a thread of its own, until stopped.

    While something else holds the port, such as a probe listener started by
    hand, it retries, and answers once the port is free. It never holds the
    port after `stop` has returned `True`.
    """

    def __init__(self, port: int, *, retry: float = 1.0, poll: float = 0.2) -> None:
        """Make a responder, which doesn't listen yet.

        Args:
            port: The port to answer on.
            retry: Seconds between tries to bind a held port.
            poll: Seconds between checks whether to stop, while listening.
        """
        self.port = port
        self._retry = retry
        self._poll = poll
        self._lock = threading.Lock()
        # Each thread gets events of its own, so that one that is still ending can't touch the next one's
        self._stop = threading.Event()
        self._listening = threading.Event()
        self._thread: threading.Thread | None = None
        # A start asked for while a thread that was told to stop still ends: that thread makes up for it
        self._restart = False

    @property
    def listening(self) -> bool:
        """Whether it holds the port and answers on it."""
        return self._listening.is_set()

    def start(self) -> None:
        """Start answering, in the background.

        Does nothing if it already runs. If a thread that was told to stop still
        hasn't ended, the new one starts once it has: two would only compete for
        the port.

        Raises:
            RuntimeError: No thread could be started; then none is kept.
        """
        with self._lock:
            # A thread that has ended, or has passed its last look at `_restart`, leaves `_thread` empty
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    logger.warning("The probe responder on port %d is still stopping: starts once it has", self.port)
                    self._restart = True
                return
            self._spawn()

    def _spawn(self) -> None:
        """Start a thread with events of its own. The caller holds the lock.

        Raises:
            RuntimeError: No thread could be started; then none is kept, so that `stop` doesn't wait for it.
        """
        self._stop = threading.Event()
        self._listening = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, args=(self._stop, self._listening), name="probe-responder", daemon=True
        )
        try:
            self._thread.start()
        except BaseException:
            self._thread = None
            raise

    def stop(self, timeout: float = 10) -> bool:
        """Stop answering, and wait until the port is closed.

        Args:
            timeout: Seconds to wait for the thread to end.

        Returns:
            Whether it ended in time, or never ran: then the port is free of it.
        """
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._restart = False
        if thread is None:
            return True
        thread.join(timeout)
        if thread.is_alive():
            logger.warning("The probe responder on port %d didn't stop in %s s", self.port, timeout)
            return False
        with self._lock:
            if self._thread is thread:
                self._thread = None
        return True

    def _serve(self, stop: threading.Event, listening: threading.Event) -> None:
        """Bind the port, retrying while it's held, and answer until told to stop.

        Args:
            stop: Set to stop.
            listening: Set while it answers.
        """
        try:
            self._bind_and_answer(stop, listening)
        finally:
            # The last look at `_restart`: from here on, `start` sees no thread, and starts one itself
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    if self._restart:
                        self._restart = False
                        self._spawn()

    def _bind_and_answer(self, stop: threading.Event, listening: threading.Event) -> None:
        """Bind the port, retrying while something else holds it, and answer until told to stop.

        Other reasons not to bind, such as a port this user may not bind, don't
        go away by waiting: then it gives up, and says so.

        Args:
            stop: Set to stop.
            listening: Set while it answers.
        """
        warned = False
        while not stop.is_set():
            try:
                server = socket.create_server(("", self.port))
            except OSError as error:
                if error.errno != errno.EADDRINUSE:
                    logger.error(
                        "The probe responder can't bind port %d (%s): no answers to probes", self.port, error.strerror
                    )
                    return
                if not warned:
                    logger.warning("The probe responder's port %d is in use: retrying", self.port)
                    warned = True
                stop.wait(self._retry)
                continue
            try:
                self._answer(server, stop, listening)
            except OSError as error:
                # Such as no descriptor left for the selector: close the port, and try again in a while
                logger.warning("The probe responder failed on port %d (%s): retrying", self.port, error.strerror)
                stop.wait(self._retry)
            finally:
                listening.clear()
                server.close()
            logger.info("The probe responder stopped answering on port %d", self.port)

    def _answer(self, server: socket.socket, stop: threading.Event, listening: threading.Event) -> None:
        """Accept connections and close them, until told to stop.

        Args:
            server: The listening socket.
            stop: Set to stop.
            listening: Set while it answers.
        """
        server.setblocking(False)
        with selectors.DefaultSelector() as selector:
            selector.register(server, selectors.EVENT_READ)
            listening.set()
            logger.info("The probe responder answers on port %d", self.port)
            while not stop.is_set():
                if not selector.select(self._poll):
                    continue
                try:
                    connection, _ = server.accept()
                except OSError:
                    # The client gave up first, or this process is out of descriptors: try again,
                    # without spinning on a connection that stays pending
                    stop.wait(self._poll)
                    continue
                connection.close()
