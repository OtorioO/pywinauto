from __future__ import unicode_literals
from __future__ import print_function

import time
import re
import ctypes
import win32api
import win32gui
import win32process
import locale
import abc

from . import SendKeysCtypes as SendKeys
from . import six
from . import win32defines, win32structures, win32functions
from .timings import Timings
from .actionlogger import ActionLogger
from . import handleprops
from .mouse import _perform_click_input
#from . import backend

#=========================================================================
def remove_non_alphanumeric_symbols(s):
    "Make text usable for attribute name"
    return re.sub("\W", "_", s)

#=========================================================================
class InvalidElement(RuntimeError):
    "Raises when an invalid element is passed"
    pass

#=========================================================================
class ElementNotEnabled(RuntimeError):
    "Raised when an element is not enabled"
    pass

#=========================================================================
class ElementNotVisible(RuntimeError):
    "Raised when an element is not visible"
    pass

#=========================================================================
@six.add_metaclass(abc.ABCMeta)
class BaseMeta(abc.ABCMeta):
    "Abstract metaclass for Wrapper objects"
    
    @staticmethod
    def find_wrapper(element):
        "Abstract static method to find appropriate wrapper"
        raise NotImplementedError()

#=========================================================================
@six.add_metaclass(BaseMeta)
class BaseWrapper(object):
    """
    Abstract wrapper for elements.

    All other wrappers are derived from this.
    """

    # Properties required for _MetaWrapper class
    friendlyclassname = None
    windowclasses = []
    controltypes = []

    # Properties that describe type of the element
    can_be_label = False
    has_title = True

    '''
    #------------------------------------------------------------
    def __new__(cls, elementInfo):
        # only use the meta class to find the wrapper for BaseWrapper
        # so allow users to force the wrapper if they want
        if cls != BaseWrapper:
            obj = object.__new__(cls)
            obj.__init__(elementInfo)
            return obj

        new_class = cls.find_wrapper(elementInfo)
        obj = object.__new__(new_class)

        obj.__init__(elementInfo)

        return obj
    '''

    #------------------------------------------------------------
    def __init__(self, elementInfo, active_backend):
        """
        Initialize the element

        * **elementInfo** is instance of int or one of ElementInfo childs
        """
        self.backend = active_backend
        if elementInfo:
            #if isinstance(elementInfo, six.integer_types):
            #    elementInfo = self.backend.element_info_class(elementInfo)

            self._elementInfo = elementInfo

            self.handle = self._elementInfo.handle
            self._as_parameter_ = self.handle

            self.ref = None
            self.appdata = None
            self._cache = {}
            self.actions = ActionLogger()
        else:
            raise RuntimeError('NULL pointer used to initialize BaseWrapper')

    #------------------------------------------------------------
    @property
    def elementInfo(self):
        """Read-only property to get *ElementInfo object"""
        return self._elementInfo

    #------------------------------------------------------------
    def FriendlyClassName(self):
        """
        Return the friendly class name for the control

        This differs from the class of the control in some cases.
        Class() is the actual 'Registered' element class of the control
        while FriendlyClassName() is hopefully something that will make
        more sense to the user.

        For example Checkboxes are implemented as Buttons - so the class
        of a CheckBox is "Button" - but the friendly class is "CheckBox"
        """
        if self.friendlyclassname is None:
            self.friendlyclassname = self._elementInfo.className
        return self.friendlyclassname

    #------------------------------------------------------------
    def Class(self):
        """Return the class name of the elenemt"""
        return self.elementInfo.className

    #------------------------------------------------------------
    def WindowText(self):
        """
        Window text of the element

        Quite  a few contorls have other text that is visible, for example
        Edit controls usually have an empty string for WindowText but still
        have text displayed in the edit window.
        """
        return self.elementInfo.richText

    #------------------------------------------------------------
    def ControlID(self):
        """
        Return the ID of the element

        Only controls have a valid ID - dialogs usually have no ID assigned.

        The ID usually identified the control in the window - but there can
        be duplicate ID's for example lables in a dialog may have duplicate
        ID's.
        """
        return self.elementInfo.controlId

    #------------------------------------------------------------
    def IsVisible(self):
        """
        Whether the element is visible or not

        Checks that both the Top Level Parent (probably dialog) that
        owns this element and the element itself are both visible.

        If you want to wait for an element to become visible (or wait
        for it to become hidden) use ``Application.Wait('visible')`` or
        ``Application.WaitNot('visible')``.

        If you want to raise an exception immediately if an element is
        not visible then you can use the BaseWrapper.VerifyVisible().
        BaseWrapper.VerifyActionable() raises if the element is not both
        visible and enabled.
        """
        return self.elementInfo.visible #and self.TopLevelParent().elementInfo.visible

    #------------------------------------------------------------
    def IsEnabled(self):
        """
        Whether the element is enabled or not

        Checks that both the Top Level Parent (probably dialog) that
        owns this element and the element itself are both enabled.

        If you want to wait for an element to become enabled (or wait
        for it to become disabled) use ``Application.Wait('visible')`` or
        ``Application.WaitNot('visible')``.

        If you want to raise an exception immediately if an element is
        not enabled then you can use the BaseWrapper.VerifyEnabled().
        BaseWrapper.VerifyReady() raises if the window is not both
        visible and enabled.
        """
        return self.elementInfo.enabled #and self.TopLevelParent().elementInfo.enabled

    #------------------------------------------------------------
    def Rectangle(self):
        """
        Return the rectangle of element

        The Rectangle() is the rectangle of the element on the screen.
        Coordinates are given from the top left of the screen.

        This method returns a RECT structure, Which has attributes - top,
        left, right, bottom. and has methods width() and height().
        See win32structures.RECT for more information.
        """
        return self.elementInfo.rectangle

    #------------------------------------------------------------
    def ClientToScreen(self, client_point):
        "Maps point from client to screen coordinates"
        rect = self.Rectangle()
        if isinstance(client_point, win32structures.POINT):
            return (client_point.x + rect.left, client_point.y + rect.top)
        else:
            return (client_point[0] + rect.left, client_point[1] + rect.top)

    #-----------------------------------------------------------
    def ProcessID(self):
        "Return the ID of process that owns this window"
        return self._elementInfo.processId

    #-----------------------------------------------------------
    def IsDialog(self):
        "Return true if the control is a top level window"
        if self.Parent():
            return self == self.TopLevelParent()
        else:
            return False

    #-----------------------------------------------------------
    def Parent(self):
        """
        Return the parent of this element

        Note that the parent of a control is not necesarily a dialog or
        other main window. A group box may be the parent of some radio
        buttons for example.

        To get the main (or top level) window then use
        BaseWrapper.TopLevelParent().
        """
        parent_elem = self._elementInfo.parent

        if parent_elem:
            return self.backend.generic_wrapper_class(parent_elem)
        else:
            return None

    #-----------------------------------------------------------
    def root(self):
        "Return wrapper for root element (desktop)"
        return self.backend.generic_wrapper_class(self.backend.element_info_class())

    #-----------------------------------------------------------
    def TopLevelParent(self):
        """
        Return the top level window of this control

        The TopLevel parent is different from the parent in that the Parent
        is the element that owns this element - but it may not be a dialog/main
        window. For example most Comboboxes have an Edit. The ComboBox is the
        parent of the Edit control.

        This will always return a valid window element (if the control has
        no top level parent then the control itself is returned - as it is
        a top level window already!)
        """

        if not ("top_level_parent" in self._cache.keys()):
            parent = self.Parent()

            if parent:
                if self.Parent() == self.root():
                    self._cache["top_level_parent"] = self
                else:
                    return self.Parent().TopLevelParent()
            else:
                self._cache["top_level_parent"] = self

        return self._cache["top_level_parent"]

    #-----------------------------------------------------------
    def Texts(self):
        """
        Return the text for each item of this control"

        It is a list of strings for the control. It is frequently over-ridden
        to extract all strings from a control with multiple items.

        It is always a list with one or more strings:

          * First elemtent is the window text of the control
          * Subsequent elements contain the text of any items of the
            control (e.g. items in a listbox/combobox, tabs in a tabcontrol)
        """
        texts = [self.WindowText(), ]
        return texts

    #-----------------------------------------------------------
    def Children(self):
        """
        Return the children of this element as a list

        It returns a list of BaseWrapper (or subclass) instances, it
        returns an empty list if there are no children.
        """
        child_elements = self._elementInfo.children
        return [self.backend.generic_wrapper_class(elementInfo) for elementInfo in child_elements]

    #-----------------------------------------------------------
    def Descendants(self):
        """
        Return the descendants of this element as a list

        It returns a list of BaseWrapper (or subclass) instances, it
        returns an empty list if there are no descendants.
        """
        desc_elements = self._elementInfo.descendants
        return [self.backend.generic_wrapper_class(elementInfo) for elementInfo in desc_elements]

    #-----------------------------------------------------------
    def ControlCount(self):
        "Return the number of children of this control"
        return len(self._elementInfo.children)

    #-----------------------------------------------------------
    def IsChild(self, parent):
        """
        Return True if this element is a child of 'parent'.

        An element is a child of another element when it is a direct of the
        other element. An element is a direct descendant of a given
        element if the parent element is the the chain of parent elements
        for the child element.
        """
        return self in parent.Children()

    #-----------------------------------------------------------
    def __eq__(self, other):
        "Returns true if 2 BaseWrapper's describe 1 actual element"
        if hasattr(other, "_elementInfo"):
            return self.elementInfo == other.elementInfo
        else:
            return self.elementInfo == other

    #-----------------------------------------------------------
    def __ne__(self, other):
        "Returns False if the elements described by 2 BaseWrapper's are different"
        return not self == other

    #-----------------------------------------------------------
    def VerifyActionable(self):
        """
        Verify that the element is both visible and enabled

        Raise either ElementNotEnalbed or ElementNotVisible if not
        enabled or visible respectively.
        """
        if self._elementInfo.handle:
            win32functions.WaitGuiThreadIdle(self)
        else:
            # TODO: get WaitGuiThreadIdle function for elements without handle
            pass
        self.VerifyVisible()
        self.VerifyEnabled()

    #-----------------------------------------------------------
    def VerifyEnabled(self):
        """
        Verify that the element is enabled

        Check first if the element's parent is enabled (skip if no parent),
        then check if element itself is enabled.
        """
        if not self.IsEnabled():
            raise ElementNotEnabled()

    #-----------------------------------------------------------
    def VerifyVisible(self):
        """
        Verify that the element is visible

        Check first if the element's parent is visible. (skip if no parent),
        then check if element itself is visible.
        """
        if not self.IsVisible():
            raise ElementNotVisible()

    #-----------------------------------------------------------
    def ClickInput(
        self,
        button = "left",
        coords = (None, None),
        button_down = True,
        button_up = True,
        double = False,
        wheel_dist = 0,
        use_log = True,
        pressed = "",
        absolute = False,
        key_down = True,
        key_up = True):
        """Click at the specified coordinates

        * **button** The mouse button to click. One of 'left', 'right',
          'middle' or 'x' (Default: 'left')
        * **coords** The coordinates to click at.(Default: center of control)
        * **double** Whether to perform a double click or not (Default: False)
        * **wheel_dist** The distance to move the mouse wheel (default: 0)

        NOTES:
           This is different from Click in that it requires the control to
           be visible on the screen but performs a more realistic 'click'
           simulation.

           This method is also vulnerable if the mouse is moved by the user
           as that could easily move the mouse off the control before the
           Click has finished.
        """
        if self.IsDialog():
            self.SetFocus()
        ctrl_text = self.WindowText()
        if isinstance(coords, win32structures.RECT):
            coords = [coords.left, coords.top]

    #    # allow points objects to be passed as the coords
        if isinstance(coords, win32structures.POINT):
            coords = [coords.x, coords.y]
    #    else:
        coords = list(coords)

        # set the default coordinates
        if coords[0] is None:
            coords[0] = int(self.Rectangle().width() / 2)
        if coords[1] is None:
            coords[1] = int(self.Rectangle().height() / 2)

        if not absolute:
            coords = self.ClientToScreen(coords)

        _perform_click_input(button, coords, double, button_down, button_up,
                             wheel_dist=wheel_dist, pressed=pressed,
                             key_down=key_down, key_up=key_up)

        if use_log:
            if ctrl_text is None:
                ctrl_text = six.text_type(ctrl_text)
            message = 'Clicked ' + self.FriendlyClassName() + ' "' + ctrl_text + \
                      '" by ' + str(button) + ' button mouse click (x,y=' + ','.join([str(coord) for coord in coords]) + ')'
            if double:
                message = 'Double-c' + message[1:]
            if button.lower() == 'move':
                message = 'Moved mouse over ' + self.FriendlyClassName() + ' "' + ctrl_text + \
                      '" to screen point (x,y=' + ','.join([str(coord) for coord in coords]) + ')'
            ActionLogger().log(message)

    #-----------------------------------------------------------
    def DoubleClickInput(self, button = "left", coords = (None, None)):
        "Double click at the specified coordinates"
        self.ClickInput(button, coords, double=True)

    #-----------------------------------------------------------
    def RightClickInput(self, coords = (None, None)):
        "Right click at the specified coords"
        self.ClickInput(button='right', coords=coords)

    #-----------------------------------------------------------
    def PressMouseInput(
            self,
            button = "left",
            coords = (None, None),
            pressed = "",
            absolute = False,
            key_down = True,
            key_up = True
    ):
        "Press a mouse button using SendInput"
        self.ClickInput(
            button=button,
            coords=coords,
            button_down=True,
            button_up=False,
            pressed=pressed,
            absolute=absolute,
            key_down=key_down,
            key_up=key_up
        )

    #-----------------------------------------------------------
    def ReleaseMouseInput(
            self,
            button = "left",
            coords = (None, None),
            pressed = "",
            absolute = False,
            key_down = True,
            key_up = True
    ):
        "Release the mouse button"
        self.ClickInput(
            button,
            coords,
            button_down=False,
            button_up=True,
            pressed=pressed,
            absolute=absolute,
            key_down=key_down,
            key_up=key_up
        )

    #-----------------------------------------------------------
    def MoveMouseInput(self, coords = (0, 0), pressed = "", absolute = False):
        "Move the mouse"
        if not absolute:
            self.actions.log('Moving mouse to relative (client) coordinates ' + str(coords).replace('\n', ', '))

        self.ClickInput(button='move', coords=coords, absolute=absolute, pressed=pressed)

        if self._elementInfo.handle:
            win32functions.WaitGuiThreadIdle(self)
        else:
            # TODO: get WaitGuiThreadIdle function for elements without handle
            pass

        return self

    #-----------------------------------------------------------
    def DragMouseInput(self,
        button = "left",
        press_coords = (0, 0),
        release_coords = (0, 0),
        pressed = "",
        absolute = False):
        "Drag the mouse"

        if isinstance(press_coords, win32structures.POINT):
            press_coords = (press_coords.x, press_coords.y)

        if isinstance(release_coords, win32structures.POINT):
            release_coords = (release_coords.x, release_coords.y)

        self.PressMouseInput(button, press_coords, pressed, absolute=absolute)
        time.sleep(Timings.before_drag_wait)
        for i in range(5):
            self.MoveMouseInput((press_coords[0]+i,press_coords[1]), pressed=pressed, absolute=absolute) # "left"
            time.sleep(Timings.drag_n_drop_move_mouse_wait)
        self.MoveMouseInput(release_coords, pressed=pressed, absolute=absolute) # "left"
        time.sleep(Timings.before_drop_wait)
        self.ReleaseMouseInput(button, release_coords, pressed, absolute=absolute)
        time.sleep(Timings.after_drag_n_drop_wait)
        return self

    #-----------------------------------------------------------
    def WheelMouseInput(self, coords = (None, None), wheel_dist = 1, pressed = ""):
        "Do mouse wheel"
        self.ClickInput(button='wheel', coords=coords, wheel_dist=wheel_dist, pressed=pressed)
        return self

    #-----------------------------------------------------------
    def TypeKeys(
        self,
        keys,
        pause = None,
        with_spaces = False,
        with_tabs = False,
        with_newlines = False,
        turn_off_numlock = True,
        set_foreground = True):
        """
        Type keys to the element using SendKeys

        This uses the SendKeys python module from
        http://www.rutherfurd.net/python/sendkeys/ .This is the best place
        to find documentation on what to use for the **keys**
        """
        self.VerifyActionable()

        if pause is None:
            pause = Timings.after_sendkeys_key_wait

        if set_foreground:
            self.SetFocus()

        # attach the Python process with the process that self is in
        if self._elementInfo.handle:
            window_thread_id, pid = win32process.GetWindowThreadProcessId(int(self.handle))
            win32functions.AttachThreadInput(win32functions.GetCurrentThreadId(), window_thread_id, win32defines.TRUE)
            # TODO: check return value of AttachThreadInput properly
        else:
            # TODO: UIA stuff maybe
            pass

        if isinstance(keys, six.text_type):
            aligned_keys = keys
        elif isinstance(keys, six.binary_type):
            aligned_keys = keys.decode(locale.getpreferredencoding())
        else:
            # convert a non-string input
            aligned_keys = six.text_type(keys)

        # Play the keys to the active window
        SendKeys.SendKeys(
            aligned_keys + '\n',
            pause,
            with_spaces,
            with_tabs,
            with_newlines,
            turn_off_numlock)

        # detach the python process from the window's process
        if self._elementInfo.handle:
            win32functions.AttachThreadInput(win32functions.GetCurrentThreadId(), window_thread_id, win32defines.FALSE)
            # TODO: check return value of AttachThreadInput properly
        else:
            # TODO: UIA stuff
            pass

        if self._elementInfo.handle:
            win32functions.WaitGuiThreadIdle(self)
        else:
            # TODO: get WaitGuiThreadIdle function for elements without handle
            pass

        self.actions.log('Typed text to the ' + self.FriendlyClassName() + ': ' + aligned_keys)
        return self

    def SetFocus(self):
        "Set the focus to this element"
        pass

#====================================================================