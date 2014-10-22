import vim
import re
import tempfile

from view  import *
from utils import *
from conn  import *

#======================== Registry ===========================================#

#
# A dictionary containing an entry for all nodes contained in the explorer
# window, keyed by guid.
#
registry = {}

def addNode(guid, node):
    registry[guid] = node

def deleteNodes():
    registry.clear()

def getNode(guid):
    if guid in registry:
        return registry[guid]
    return None 

#======================== Node ===============================================#

class Node(object):
    def __init__(self, indent=0):
        self.parent    = None
        self.children  = []
        self.row       = -1
        self.indent    = indent
        self.prefWidth = 0
        self.close()

    def activate(self):
        self.toggle()

    def addChild(self, node):
        node.parent = self
        self.children.append(node)

    def close(self):
        self.expanded = False

    def commitChanges(self):
        pass

    def expand(self):
        self.expanded = True

    def getPreferredWidth(self):
        if self.parent is None or self.parent.isExpanded():
            return self.prefWidth
        return 0

    def isExpanded(self):
        return self.expanded is True

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

    def addNote(self, note):
        node = NoteNode(note, self.indent + 1)
        addNode(note.guid, node)

        self.addChild(node)

    def commitChanges(self):
        if self.notebook.name != self.name:
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

    def getNotes(self):
        searchWords = 'notebook:"%s"' % self.notebook.name
        return GeeknoteGetNotes(searchWords)

    def render(self, buffer):
        numNotes = len(self.children)

        if self.expanded is False:
            if self.loaded and numNotes == 0:
                line = '-'
            else:
                line = '+'
        else:
            line = '-'

        line += ' ' + self.name
        self.prefWidth = len(line)

        buffer.append('{:<50} [{}]'.format(line, self.notebook.guid))
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

        self.note = note
        self.notebookGuid = note.notebookGuid
        self.setTitle(note.title)

    def activate(self):
        super(NoteNode, self).activate()

        # TODO: move all of this into view.py
        origWin        = getActiveWindow()
        prevWin        = getPreviousWindow()
        firstUsableWin = getFirstUsableWindow()
        isPrevUsable   = isWindowUsable(prevWin)
        
        setActiveWindow(prevWin)
        if (isPrevUsable is False) and (firstUsableWin == -1):
            vim.command('botright vertical new')
        elif isPrevUsable is False:
            setActiveWindow(firstUsableWin)

        GeeknoteOpenNote(self.note)
        setActiveWindow(origWin)
        return

    def commitChanges(self):
        if self.note.title != self.title:
            self.note.title = self.title
            GeeknoteUpdateNote(self.note)

        if self.note.notebookGuid != self.notebookGuid:
            self.note.notebookGuid = self.notebookGuid
            GeeknoteUpdateNote(self.note)

    def render(self, buffer):
        line  = ' ' * (self.indent * 4)
        line += self.title

        self.prefWidth = len(line)

        line = '{:<50} [{}]'.format(line, self.note.guid)
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

        # FIXME
        if note.guid not in registry:
            addNode(note.guid, node)

        self.addChild(node)

    def expand(self):
        if self.loaded is False:
            notes = self.getNotes()
            notes.sort(key=lambda n: n.title)
            for note in notes:
                self.addNote(note)
            self.loaded = True

        super(TagNode, self).expand()

    def getNotes(self):
        searchWords = 'tag:"%s"' % self.tag.name
        return GeeknoteGetNotes(searchWords)

    def render(self, buffer):
        numNotes = len(self.children)

        if self.expanded is False:
            if self.loaded and numNotes == 0:
                line = '-'
            else:
                line = '+'
        else:
            line = '-'

        line += ' ' + self.name
        self.prefWidth = len(line)

        if numNotes != 0:
            line += ' (%d)' % numNotes

        buffer.append('{:<50} [{}]'.format(line, self.tag.guid))
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

        self.refresh()

        self.dataFile = tempfile.NamedTemporaryFile(delete=True)

        autocmd('BufWritePre' , 
                self.dataFile.name, 
                ':call Vim_GeeknoteCommitStart()')

        autocmd('BufWritePre' , 
                self.dataFile.name, 
                ':call Vim_GeeknoteCommitComplete()')

        autocmd('VimLeave', '*', ':call Vim_GeeknoteTerminate()')

    def __del__(self):
        try:
            self.dataFile.close()
        except:
            pass

    def activateNode(self, line):
        guid = self.getNodeGuid(line)
        if guid is not None:
            node = getNode(guid)
            node.activate()

            # Rerender the navigation window. Keep the current cursor postion.
            row, col = vim.current.window.cursor
            self.render()
            vim.current.window.cursor = (row, col)

    def addNote(self, note):
        notebook = getNode(note.notebookGuid)
        notebook.addNote(note) 

    def addNotebook(self, notebook):
        node = NotebookNode(notebook)
        self.notebooks.append(node)
        self.notebooks.sort(key=lambda n: n.notebook.name.lower())

        addNode(notebook.guid, node)

    def addTag(self, tag):
        tagNode = TagNode(tag)
        self.tags.append(tagNode)
        self.tags.sort(key=lambda t: t.tag.name.lower())

        addNode(tag.guid, tagNode)

    def applyChanges(self):
        if isBufferModified(self.buffer.number) is False:
            return

        for row in xrange(len(self.buffer)):
            line = self.buffer[row]

            # Look for changes to notes.
            r = re.compile('^\s+(.+)\[(.+)\]$')
            m = r.match(line)
            if m: 
                title = m.group(1).strip()
                guid  = m.group(2)
                node  = getNode(guid)
                if isinstance(node       , NoteNode) and \
                   isinstance(node.parent, NotebookNode):

                    # Did the user change the note's title?
                    if title != node.title:
                        node.setTitle(title)
                        if node not in self.modifiedNodes:
                            self.modifiedNodes.append(node)

                    # Did the user move the note into a different notebook?
                    newParent = self.findNotebookForNode(row)
                    if newParent is not None:
                        if newParent.notebook.guid != node.notebookGuid:
                            oldParent = getNode(node.notebookGuid)
                            node.notebookGuid = newParent.notebook.guid

                            newParent.expand()
                            newParent.addChild(node)
                            oldParent.removeChild(node)

                            if node not in self.modifiedNodes:
                                self.modifiedNodes.append(node)
                continue

            # Look for changes to notebooks.
            r = re.compile('^[\+-](.+)\[(.+)\]$')
            m = r.match(line)
            if m:
                name = m.group(1).strip()
                guid = m.group(2)
                node = getNode(guid)
                if isinstance(node, NotebookNode):
                    if name != node.name:
                        node.setName(name)
                        self.modifiedNodes.append(node)
                continue

    def commitChanges(self):
        self.applyChanges()
        for node in self.modifiedNodes:
            node.commitChanges()
        del self.modifiedNodes[:]

    #
    # Search upwards, starting at the given row number and return the first
    # note nodebook found. 
    #
    def findNotebookForNode(self, nodeRow):
        while nodeRow > 0:
            guid = self.getNodeGuid(self.buffer[nodeRow])
            if guid is not None: 
                node = getNode(guid)
                if isinstance(node, NotebookNode):
                    return node
            nodeRow -= 1
        return None

    def getSelectedNotebook(self):
        if self.buffer is None:
            return None

        prevWin = getActiveWindow()
        setActiveBuffer(self.buffer)
        text = vim.current.line
        setActiveWindow(prevWin)

        guid = self.getNodeGuid(text)
        if guid is not None:
            node = getNode(guid)
            if isinstance(node, NotebookNode):
                return node.notebook
            if isinstance(node, NoteNode):
                return getNode(node.notebookGuid)
        return None

    def getNodeGuid(self, nodeText):
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
        setBufferVariable(bnum, 'buftype'    , 'quickfix')
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
        if int(vim.eval('exists("g:GeeknoteNotebooks")')):
            guids = vim.eval('g:GeeknoteNotebooks')
            for guid in guids:
                notebook = GeeknoteGetNotebook(guid)
                if notebook is not None:
                    self.addNotebook(notebook)
        else:
            notebooks = GeeknoteGetNotebooks()
            for notebook in notebooks:
                self.addNotebook(notebook)

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
        self.applyChanges()

        # Clear the navigation buffer to get rid of old content (if any).
        del self.buffer[:]

        # Prepare the new content and append it to the navigation buffer.
        content = []
        content.append('Notebooks:')
        content.append('{:=^90}'.format('='))

        # Render notebooks, notes, and tags
        for node in self.notebooks:
            node.render(content)

        content.append('')
        content.append('Tags:')
        content.append('{:=^90}'.format('='))

        for node in self.tags:
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
        for guid in self.expandState:
            node = getNode(guid)
            if node is not None:
                if self.expandState[guid]:
                    node.expand()
                else:
                    node.close()

    def saveExpandState(self):
        for node in self.notebooks:
            self.expandState[node.notebook.guid] = node.expanded

        for node in self.tags:
            self.expandState[node.tag.guid] = node.expanded

    def selectNode(self, node):
        self.selectedNode = node

        # Move the cursor over the node if the node has been rendered.
        if node.row != -1:
            origWin = getActiveWindow()
            setActiveBuffer(self.buffer)
            vim.current.window.cursor = (node.row, 0)
            setActiveWindow(origWin)

    def selectNote(self, note):
        node = getNode(note.notebookGuid)
        if node is not None:
            node = getNode(note.notebookGuid)
            node.expand()

        node = getNode(note.guid)
        self.selectNode(node)

    def selectNotebook(self, notebook):
        node = getNode(notebook.guid)
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

