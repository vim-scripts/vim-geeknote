import vim
import re
import tempfile

from view  import *
from utils import *
from conn  import *

#======================== Global Setup/Config ================================#

ExplorerCharOpened = u'\u25bd'
ExplorerCharClosed = u'\u25b6'

if int(vim.eval('exists("g:GeeknoteExplorerNodeOpened")')):
    ExplorerCharOpened = vim.eval(
        'g:GeeknoteExplorerNodeOpened').decode('utf8')

if int(vim.eval('exists("g:GeeknoteExplorerNodeClosed")')):
    ExplorerCharClosed = vim.eval(
        'g:GeeknoteExplorerNodeClosed').decode('utf8')

#======================== Registry ===========================================#

#
# A dictionary containing an entry for all nodes contained in the explorer
# window, keyed by guid.
#
registry = {}

#
# Maps GUIDs to instance numbers. Each node represents an object. Objects are
# unique but nodes are not. There can be any number nodes instanciated for an
# object.  An instance number is used to distinguish nodes for the same object.
# This container maps an object's GUID to the maximum instance number of any
# node representing the object (i.e. object node count minus one).
#
instanceMap = {}

def registerNode(node):
    guid = node.getGuid()
    if guid not in instanceMap:
        instance = 0
    else:
        instance = instanceMap[guid] + 1

    instanceMap[guid] = instance

    key = guid + "(" + str(instance) + ")"
    node.setKey(key)
    registry[key] = node

def deleteNodes():
    registry.clear()

def getNode(key):
    if key in registry:
        return registry[key]
    return None 

def getNodeByInstance(guid, instance):
    key = guid + "(" + str(instance) + ")"
    return getNode(key)

#======================== Node ===============================================#

class Node(object):
    def __init__(self, indent=0):
        self.parent    = None
        self.children  = []
        self.row       = -1
        self.indent    = indent
        self.prefWidth = 0
        self.key       = ""
        self.close()

    def activate(self):
        self.toggle()

    def adapt(self, line):
        return False

    def addChild(self, node):
        node.parent = self
        self.children.append(node)

    def close(self):
        self.expanded = False

    def commitChanges(self):
        pass

    def expand(self):
        self.expanded = True

    def getGuid(self):
        return "None"

    def getKey(self):
        return self.key

    def getPreferredWidth(self):
        if self.parent is None or self.parent.isExpanded():
            return self.prefWidth
        return 0

    def isExpanded(self):
        return self.expanded is True

    def refresh(self):
        pass

    def setKey(self, key):
        self.key = key

    def removeChild(self, node):
        if node in self.children:
            self.children.remove(node)

    def setName(self, name):
        self.name = name

    def toggle(self):
        if self.expanded:
            self.close()
        else:
            self.expand()

#======================== NotebookNode =======================================#

class NotebookNode(Node):
    def __init__(self, notebook):
        super(NotebookNode, self).__init__()

        self.notebook = notebook
        self.loaded   = False
        self.setName(notebook.name)

    def adapt(self, line):
        if len(self.children) > 0:
            r = re.compile("^\S+"     # match leading non-whitespace characters 
                           "(?:\s+)?" # optional whitespace
                           "(.*)"     # notebook name
                           "\(\d+\)"  # note count
                           "(?:\s+)?" # optional whitespace
                           "N\[.*\]"  # key
                           ".*$")     # everything else till end of line
        else:
            r = re.compile("^\S+"     # match leading non-whitespace characters
                           "(?:\s+)?" # optional whitespace
                           "(.*)"     # notebook name
                           "N\[.*\]"  # key
                           ".*$")     # everything else till end of line

        m = r.match(line)
        if m:
            name = m.group(1).strip()
            if self.name != name:
                self.setName(name)
                return True
        else:
            print line

        return False

    def addNote(self, note):
        node = NoteNode(note, self.indent + 1)
        registerNode(node)

        self.addChild(node)
        return node

    def commitChanges(self):
        self.notebook.name = self.name
        GeeknoteUpdateNotebook(self.notebook)

    def expand(self):
        if self.loaded is False:
            del self.children[:]

            notes = self.getNotes()

            for note in notes:
                self.addNote(note)
            self.loaded = True

        super(NotebookNode, self).expand()

    def getGuid(self):
        return self.notebook.guid

    def getNotes(self):
        searchWords = 'notebook:"%s"' % self.notebook.name
        return GeeknoteGetNotes(searchWords)

    def render(self, buffer):
        numNotes = len(self.children)

        if self.expanded:
            line = ExplorerCharOpened
        else:
            if self.loaded and numNotes == 0:
                line = ExplorerCharOpened
            else:
                line = ExplorerCharClosed

        line += ' ' + self.name.decode('utf8')
        if numNotes != 0:
            line += ' (%d)' % numNotes

        line = line.encode('utf8')
        self.prefWidth = len(line)

        buffer.append('{:<50} N[{}]'.format(line, self.getKey()))
        self.row = len(buffer)

        if self.expanded:
            for noteNode in self.children:
                noteNode.render(buffer)

    def setName(self, name):
        self.name = name

#======================== NoteNode ===========================================#

class NoteNode(Node):
    def __init__(self, note, indent=1):
        super(NoteNode, self).__init__(indent)

        self.note  = note
        self.title = None
        self.refresh()

    def adapt(self, line):
        # Was the note renamed?
        r = re.compile("^\s+"    # leading whitespace
                       "(.*)"    # note title
                       "n\[.*\]" # key
                       ".*$")    # everything else till end of line
        m = r.match(line)
        if m:
            title = m.group(1).strip()
            if self.title != title:
                self.setTitle(title)
                return True
        return False

    def activate(self):
        super(NoteNode, self).activate()

        GeeknoteOpenNote(self.note)

    def commitChanges(self):
        if self.note.title != self.title:
            self.note.title = self.title
            GeeknoteUpdateNote(self.note)

        if self.note.notebookGuid != self.notebookGuid:
            self.note.notebookGuid = self.notebookGuid
            GeeknoteUpdateNote(self.note)

    def getGuid(self):
        return self.note.guid

    def refresh(self):
        if self.title is not None:
            self.note = GeeknoteRefreshNoteMeta(self.note)

        self.notebookGuid = self.note.notebookGuid
        self.setTitle(self.note.title)

    def getGuid(self):
        return self.note.guid

    def render(self, buffer):
        line  = ' ' * (self.indent * 4)
        line += self.title.decode('utf8')

        self.prefWidth = len(line)

        line = '{:<48} n[{}]'.format(line, self.getKey())
        buffer.append(line)
        self.row = len(buffer)

    def setTitle(self, title):
        self.title = title

#======================== TagNode ============================================#

class TagNode(Node):
    def __init__(self, tag, indent=0):
        super(TagNode, self).__init__(indent)

        self.tag    = tag
        self.loaded = False
        self.setName(tag.name)

    def addNote(self, note):
        node = NoteNode(note, self.indent + 1)
        registerNode(node)

        self.addChild(node)
        return node

    def expand(self):
        if self.loaded is False:
            notes = self.getNotes()
            notes.sort(key=lambda n: n.title)
            for note in notes:
                self.addNote(note)
            self.loaded = True

        super(TagNode, self).expand()

    def getGuid(self):
        return self.tag.guid

    def getNotes(self):
        searchWords = 'tag:"%s"' % self.tag.name
        return GeeknoteGetNotes(searchWords)

    def render(self, buffer):
        numNotes = len(self.children)

        if self.expanded:
            line = ExplorerCharOpened
        else:
            if self.loaded and numNotes == 0:
                line = ExplorerCharOpened
            else:
                line = ExplorerCharClosed

        line += ' ' + self.name.decode('utf8')
        if numNotes != 0:
            line += ' (%d)' % numNotes

        line = line.encode('utf8')
        self.prefWidth = len(line)

        buffer.append('{:<50} T[{}]'.format(line, self.getKey()))

        self.row = len(buffer)

        if self.expanded:
            for noteNode in self.children:
                noteNode.render(buffer)

#======================== Explorer ===========================================#

class Explorer(object):
    def __init__(self):
        self.hidden        = True
        self.selectedNode  = None
        self.notebooks     = []
        self.tags          = []
        self.modifiedNodes = []
        self.dataFile      = None
        self.buffer        = None
        self.expandState   = {}
        self.searchResults = []

        self.refresh()

        self.dataFile = tempfile.NamedTemporaryFile(delete=True)

        autocmd('BufWritePre' , 
                self.dataFile.name, 
                ':call Vim_GeeknoteCommitStart()')

        autocmd('BufWritePost', 
                self.dataFile.name, 
                ':call Vim_GeeknoteCommitComplete()')

        autocmd('VimLeave', '*', ':call Vim_GeeknoteTerminate()')

    def __del__(self):
        try:
            self.dataFile.close()
        except:
            pass

    def activateNode(self, line):
        key = self.getNodeKey(line)
        if key is not None:
            node = getNode(key)
            node.activate()

            # Rerender the navigation window. Keep the current cursor postion.
            row, col = vim.current.window.cursor
            self.render()
            vim.current.window.cursor = (row, col)

    def addNote(self, note):
        notebook = getNodeByInstance(note.notebookGuid, 0)
        notebook.expand()

        node = notebook.addNote(note) 
        self.selectNode(node)

    def addNotebook(self, notebook):
        node = NotebookNode(notebook)
        self.notebooks.append(node)
        self.notebooks.sort(key=lambda n: n.notebook.name.lower())

        registerNode(node)

        self.selectNode(node)

    def addSearchResults(self, results):
        for note in results:
            node = NoteNode(note, 0)
            registerNode(node)
            self.searchResults.append(node)

    def addTag(self, tag):
        tagNode = TagNode(tag)
        self.tags.append(tagNode)
        self.tags.sort(key=lambda t: t.tag.name.lower())

        registerNode(tagNode)

    def applyChanges(self):
        for row in xrange(len(self.buffer)):
            line = self.buffer[row]
            key  = self.getNodeKey(line)
            if key is not None:
                node = getNode(key)

                # Adapt the node based on it's current text.
                modified = node.adapt(line)

                # If the node represents a note, check to see if it was moved.
                if isinstance(node       , NoteNode) and \
                   isinstance(node.parent, NotebookNode):
                    parent = self.getNodeParent(row)
                    if (node.parent != parent):
                        node.notebookGuid = parent.notebook.guid
                        parent.expand()

                        node.parent.removeChild(node)
                        parent.addChild(node)

                        modified = True

                if modified:
                    if node not in self.modifiedNodes:
                        self.modifiedNodes.append(node)

    def clearSearchResults(self):
        del self.searchResults[:]

    def commitChanges(self):
        if isBufferModified(self.buffer.number):
            self.applyChanges()

        for node in self.modifiedNodes:
            node.commitChanges()

        for node in self.modifiedNodes:
            for key in registry:
                tempNode = getNode(key)
                if tempNode.getGuid() == node.getGuid():
                    if tempNode.getKey() != node.getKey():
                        tempNode.refresh()

        del self.modifiedNodes[:]

    def getNodeParent(self, row):
        key  = self.getNodeKey(self.buffer[row])
        node = getNode(key)

        # Only notes have parents
        if not isinstance(node, NoteNode):
            return None

        while row > 0:
            key = self.getNodeKey(self.buffer[row])
            if key is not None: 
                node = getNode(key)
                if not isinstance(node, NoteNode):
                    return node
            row -= 1

        return None

    def getSelectedNotebook(self):
        if self.buffer is None:
            return None

        prevWin = getActiveWindow()
        setActiveBuffer(self.buffer)
        text = vim.current.line
        setActiveWindow(prevWin)

        key = self.getNodeKey(text)
        if key is not None:
            node = getNode(key)
            if isinstance(node, NotebookNode):
                return node.notebook
            if isinstance(node, NoteNode): 
                if isinstance(node.parent, NotebookNode):
                    node = getNode(node.parent.getKey())
                    return node.notebook
        return None

    def getNodeKey(self, nodeText):
        r = re.compile('^.+\[(.+)\]$')
        m = r.match(nodeText)
        if m: 
            return m.group(1)
        return None

    #
    # Hide the navigation buffer. This closes the window it is displayed in but
    # does not destroy the buffer itself.
    #
    def hide(self):
        vim.command('{}bunload'.format(self.buffer.number))
        self.hidden = True

    def initView(self):
        origWin = getActiveWindow()
        setActiveBuffer(self.buffer)

        wnum = getActiveWindow()
        bnum = self.buffer.number

        setWindowVariable(wnum, 'winfixwidth', True)
        setWindowVariable(wnum, 'wrap'       , False)
        setWindowVariable(wnum, 'cursorline' , True)
        setBufferVariable(bnum, 'swapfile'   , False)
        setBufferVariable(bnum, 'bufhidden'  , 'hide')

        vim.command('setfiletype geeknote')
        setActiveWindow(origWin)

    #
    # Is the navigation buffer hidden? When hidden, the buffer exists but is
    # not active in any window.
    #
    def isHidden(self):
        return self.hidden

    def refresh(self):
        self.saveExpandState()
        deleteNodes()

        self.noteCounts = GeeknoteFindNoteCounts()

        del self.notebooks[:]
        self.refreshNotebooks()

        del self.tags[:]
        tags = GeeknoteGetTags()
        for tag in tags:
            self.addTag(tag)
        self.restoreExpandState()

        if self.selectedNode is None:
            notebook = GeeknoteGetDefaultNotebook()
            self.selectNotebook(notebook)

    def refreshNotebooks(self):
        #
        # If the user already specified which notebooks to load, load just
        # those notebooks.
        #
        if int(vim.eval('exists("g:GeeknoteNotebooks")')):
            guids = vim.eval('g:GeeknoteNotebooks')
            for guid in guids:
                notebook = GeeknoteGetNotebook(guid)
                if notebook is not None:
                    self.addNotebook(notebook)
            return

        #
        # Otherwise, load all notebooks and apply any filters that the user
        # specified (if any).
        #
        notebooks = GeeknoteGetNotebooks()
        if not int(vim.eval('exists("g:GeeknoteNotebookFilters")')):
            for notebook in notebooks:
                self.addNotebook(notebook)
        else:
            regex = []
            filters = vim.eval('g:GeeknoteNotebookFilters')
            for filter in filters:
                try:
                    r = re.compile(filter)
                    regex.append(r)
                except:
                    pass

            for notebook in notebooks:
                for r in regex:
                    if r.search(notebook.name):
                        self.addNotebook(notebook)
                        break

    # Render the navigation buffer in the navigation window..
    def render(self):
        if self.buffer is None:
            return

        origWin = getActiveWindow()
        setActiveBuffer(self.buffer)

        # 
        # Before overwriting the navigation window, look for any changes made
        # by the user. Do not synchronize them yet with the server, just make
        # sure they are not lost.
        #
        if isBufferModified(self.buffer.number):
            self.applyChanges()

        # Clear the navigation buffer to get rid of old content (if any).
        del self.buffer[:]

        # Prepare the new content and append it to the navigation buffer.
        content = []
        content.append('Notebooks:')
        content.append('{:=^92}'.format('='))

        # Render notebooks, notes, tags, and search results
        for node in self.notebooks:
            node.render(content)

        if len(self.tags) > 0:
            content.append('')
            content.append('Tags:')
            content.append('{:=^92}'.format('='))

            for node in self.tags:
                node.render(content)

        if len(self.searchResults) > 0:
             content.append('')
             content.append('Search Results:')
             content.append('{:=^92}'.format('='))

             for node in self.searchResults:
                 node.render(content)

        # Write the content list to the buffer starting at row zero.
        self.buffer.append(content, 0)

        # Move the cursor over the selected node (if any)
        if self.selectedNode is not None:
            if self.selectedNode.row != -1:
                vim.current.window.cursor = (self.selectedNode.row, 0)

        # Resize the window as appropriate.
        self.resize()

        #
        # Write the navigation window but disable BufWritePre events before
        # doing so. We only want to check for user changes when the user was
        # the one that saved the buffer.
        #
        ei = vim.eval('&ei')
        vim.command('set ei=BufWritePre')
        vim.command("write!")
        vim.command('set ei={}'.format(ei))

        setActiveWindow(origWin)

    def resize(self):
        # Fix the width if requested.
        if int(vim.eval('exists("g:GeeknoteExplorerWidth")')):
            width = int(vim.eval('g:GeeknoteExplorerWidth'))
            vim.command("vertical resize %d" % width)
            return

        # Otherwise, resize it based on content and caps. 
        maxWidth = 0
        for key in registry:
            width = getNode(key).getPreferredWidth()
            if width > maxWidth:
                maxWidth = width

        hpad = numberwidth() + foldcolumn() + 1
        maxWidth += hpad

        if int(vim.eval('exists("g:GeeknoteMaxExplorerWidth")')):
            width = int(vim.eval('g:GeeknoteMaxExplorerWidth'))
            if width < maxWidth:
                maxWidth = width
        vim.command("vertical resize %d" % maxWidth)

    def restoreExpandState(self):
        for key in self.expandState:
            node = getNode(key)
            if node is not None:
                if self.expandState[key]:
                    node.expand()
                else:
                    node.close()

    def saveExpandState(self):
        for node in self.notebooks:
            self.expandState[node.getKey()] = node.expanded

        for node in self.tags:
            self.expandState[node.getKey()] = node.expanded

    def selectNode(self, node):
        self.selectedNode = node

        # Move the cursor over the node if the node has been rendered.
        if node.row != -1:
            origWin = getActiveWindow()
            setActiveBuffer(self.buffer)
            vim.current.window.cursor = (node.row, 0)
            setActiveWindow(origWin)

    def selectNotebook(self, notebook):
        #
        # Notebooks never have more than one assoicated node, therefore, use
        # zero for the instance number.
        #
        node = getNodeByInstance(notebook.guid, 0)
        if node is not None:
            self.selectNode(node)

    def selectNotebookIndex(self, index):
        if index < len(self.notebooks):
            node = self.notebooks[index]
            self.selectNode(node)

    # Switch to the navigation buffer in the currently active window.
    def show(self):
        vim.command('topleft 50 vsplit {}'.format(self.dataFile.name))
        self.buffer = vim.current.buffer

        self.initView()
        self.render()

        noremap("<silent> <buffer> <cr>", 
            ":call Vim_GeeknoteActivateNode()<cr>")

        self.hidden = False

