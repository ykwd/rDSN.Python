from MonitorCodeDefinition import *

from paste.cascade import Cascade
from paste import httpserver
import webapp2
import sys
import os
import inspect
import threading
import thread
import webob.static 
import urllib2
import cgi
from StringIO import StringIO
from ctypes import *
from dev.python.NativeCall import *
import jinja2
import ast
import subprocess
import json
import psutil
import mimetypes
import shutil
import sqlite3
import platform
import uuid
import socket

sys.path.append(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))) + '/app_package')

#path helper functions
def GetMonitorDirPath():
    return os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

#jinja helper functions
def jinja_max(a,b):
    return max(a,b)

#check if table we need exist. If not, we create one
def check_table(cursor) :
    sql_cmd = "CREATE TABLE IF NOT EXISTS pack (name text, author text, desciprtion text, uuid text, cluster_type text, schema_info text, schema_type text, server_type text, parameters text)"
    cursor.execute(sql_cmd)

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)
JINJA_ENVIRONMENT.globals.update(jinja_max=jinja_max)


class StaticFileHandler(webapp2.RequestHandler):
    path = ''
    def get(self, path):
        abs_path = os.path.abspath(os.path.join(self.path, path))
        if os.path.isdir(abs_path)  != 0:
            self.response.set_status(403)
            return
        try:
            f = open(abs_path, 'rb')
            self.response.headers.add_header('Content-Type', mimetypes.guess_type(abs_path)[0])
            self.response.out.write(f.read())
            f.close()
        except:
            self.response.set_status(404)

class AppStaticFileHandler(StaticFileHandler):
    def __init__(self, request, response):
        # Set self.request, self.response and self.app.
        self.initialize(request, response)
        self.path = './'

class LocalStaticFileHandler(StaticFileHandler):
    def __init__(self, request, response):
        # Set self.request, self.response and self.app.
        self.initialize(request, response)
        self.path = GetMonitorDirPath() + '/local/'

#webapp2 handlers

class BaseHandler(webapp2.RequestHandler):
    def render_template(self, view_filename, params=None):
        if not params:
            params = {}
        path = 'static/view/' + view_filename

        template = JINJA_ENVIRONMENT.get_template(path)
        self.response.out.write(template.render(params))
    def SendJson(self, r):
        self.response.headers['content-type'] = 'text/plain'
        self.response.write(json.dumps(r))


    def geneRelate(self,task_code,params):
        task_list = sorted(ast.literal_eval(Native.dsn_cli_run('pq task_list')))
        call_list = ast.literal_eval(Native.dsn_cli_run('pq call '+task_code))
        callee_list = call_list[0]
        caller_list = call_list[1]

        task_dict = {}
        call_task_list = []
        link_list = []

        task_dict[task_code] = 0
        call_task_list.append(task_code)
        for task in callee_list:
            if task['name'] not in task_dict:
                task_dict[task['name']] = len(task_dict)
                call_task_list.append(task['name'])
            link_list.append({"source":task_dict[task_code],"target":task_dict[task['name']],"value":task['num']})
        for task in caller_list:
            if task['name'] not in task_dict:
                task_dict[task['name']] = len(task_dict)
                call_task_list.append(task['name'])
            link_list.append({"source":task_dict[task['name']],"target":task_dict[task_code],"value":task['num']})

        for callee in callee_list:
            single_list = ast.literal_eval(Native.dsn_cli_run('pq call '+callee['name']))[0]
            for task in single_list:
                if task['name'] not in task_dict:
                    task_dict[task['name']] = len(task_dict)
                    call_task_list.append(task['name'])
                link_list.append({"source":task_dict[callee['name']],"target":task_dict[task['name']],"value":task['num']})

        for caller in caller_list:
            single_list = ast.literal_eval(Native.dsn_cli_run('pq call '+caller['name']))[1]
            for task in single_list:
                if task['name'] not in task_dict:
                    task_dict[task['name']] = len(task_dict)
                    call_task_list.append(task['name'])
                link_list.append({"source":task_dict[task['name']],"target":task_dict[caller['name']],"value":task['num']})
        

        sharer_list = ast.literal_eval(Native.dsn_cli_run('pq pool_sharer '+task_code))
        params['TASK_CODE'] = task_code
        params['TASK_LIST'] = task_list
        params['CALLER_LIST'] = caller_list
        params['CALLEE_LIST'] = callee_list
        params['CALL_TASK_LIST'] = call_task_list 
        params['LINK_LIST'] = link_list
        params['SHARER_LIST'] = sharer_list

#webapp2 handlers
class PageMainHandler(BaseHandler):
    def get(self):
        params = {}
        params['IFMETA'] = 'meta' in Native.dsn_cli_run('engine')
        self.render_template('main.html',params)

class PageTableHandler(BaseHandler):
    def get(self):
        queryRes = ast.literal_eval(Native.dsn_cli_run('pq table'))
        curr_percent = self.request.get('curr_percent')
        if curr_percent == '':
            curr_percent = '50'
        params = {
            'TABLE': queryRes,
            'CURR_PERCENT': curr_percent,
        }
        self.render_template('table.html',params)

class PageSampleHandler(BaseHandler):
    def get(self):
        params = {}
        task_code = self.request.get('task_code')
        if task_code=='':
            task_code = 'RPC_NFS_COPY'
        self.geneRelate(task_code,params)

        remote_address = self.request.get('remote_address')
        remote_queryRes = []
        if remote_address != '':
            params['REMOTE_ADDRESS'] = remote_address
            remote_queryRes = list(ast.literal_eval(urllib2.urlopen("http://"+remote_address+"/api/remoteCounterSample?task_code="+task_code).read()))
            
        queryRes = list(ast.literal_eval(Native.dsn_cli_run('pq counter_sample '+task_code)))
        xtitles = []
        xtitles2 = []
        remote_mode = ''

        if remote_address !='':
            remote_mode = 'yes'
            tabledata = [queryRes[1][index] if len(queryRes[1][index])>1 else remote_queryRes[1][index] for index in range(len(queryRes[1]))]
            xtitles = queryRes[0][0:3]
            xtitles2 = queryRes[0][3:6]
        else:
            tabledata = queryRes[1]
            xtitles = queryRes[0]

        params['PAGE'] = 'sample.html'
        params['XTITLES'] = xtitles
        params['XTITLES2'] = xtitles2
        params['REMOTE_MODE'] = remote_mode
        params['TABLEDATA'] = tabledata
        params['COMPAREBUTTON'] = 'no'
        self.render_template('sample.html',params)

class PageValueHandler(BaseHandler):
    def get(self):
        params = {}
        task_code = self.request.get('task_code')
        if task_code=='':
            task_code = 'RPC_NFS_COPY'

        queryRes =  ast.literal_eval(Native.dsn_cli_run('pq counter_realtime '+task_code))
        params['PAGE'] = 'value.html'
        params['TABLEDATA'] = queryRes['data']
        self.geneRelate(task_code,params)

        self.render_template('value.html',params)    
class PageBarHandler(BaseHandler):
    def get(self):
        params = {}
        task_code = self.request.get('task_code')
        if task_code=='':
            task_code = 'RPC_NFS_COPY'
        self.geneRelate(task_code,params)

        ifcompare = self.request.get('ifcompare');
        if ifcompare=='':
            ifcompare = 'no'

        curr_percent = self.request.get('curr_percent')
        params['CURR_PERCENT'] = curr_percent if curr_percent != '' else '50'

        queryRes = list(ast.literal_eval(Native.dsn_cli_run('pq counter_calc '+task_code + ' ' + curr_percent if curr_percent != '50' else '')))

        remote_address = self.request.get('remote_address')
        remote_queryRes = []
        if remote_address != '':
            params['REMOTE_ADDRESS'] = remote_address
            remote_queryRes = list(ast.literal_eval(urllib2.urlopen("http://"+remote_address+"/api/remoteCounterCalc?task_code="+task_code).read()))
        
            if (queryRes[0]==0 and queryRes[1]==0 and queryRes[2]==0):
                queryRes[0] = remote_queryRes[0]
                queryRes[1] = remote_queryRes[1]
                queryRes[2] = remote_queryRes[2]
            if (queryRes[3]==0 and queryRes[4]==0 and queryRes[5]==0):
                queryRes[3] = remote_queryRes[3]
                queryRes[4] = remote_queryRes[4]
                queryRes[5] = remote_queryRes[5]

        tabledata = {}
        tabledata['nc']=[(queryRes[3]-queryRes[0])/2]
        tabledata['qs']=[queryRes[1]]
        tabledata['es']=[queryRes[2]]
        tabledata['nr']=tabledata['nc']
        tabledata['qc']=[queryRes[4]]
        tabledata['ec']=[queryRes[5]]
        tabledata['a']=[queryRes[6]]
        
        if ifcompare=='yes':
            sharer_list = ast.literal_eval(Native.dsn_cli_run('pq pool_sharer '+task_code))
            #compare_list = sorted(sharer_list,key=lambda sharer: float(ast.literal_eval(Native.dsn_cli_run('pq counter_calc '+sharer))[2])*float(ast.literal_eval(Native.dsn_cli_run('pq counter_raw '+sharer))[7]),reverse=True)[:16]
            compare_list = sorted(sharer_list,key=lambda sharer: float(ast.literal_eval(Native.dsn_cli_run('pq counter_calc '+sharer))[2]),reverse=True)[:16]
            compare_list = [elem for elem in compare_list if ast.literal_eval(Native.dsn_cli_run('pq counter_calc '+elem))[2]!=0]
            for compare_item in compare_list:
                if compare_item=='' or '_ACK' in compare_item:
                    continue
                item_data = ast.literal_eval(Native.dsn_cli_run('pq counter_calc '+compare_item))
                tabledata['nc'].append(item_data[0])
                tabledata['qs'].append(item_data[1])
                tabledata['es'].append(item_data[2])
                tabledata['nr'].append(item_data[3])
                tabledata['qc'].append(item_data[4])
                tabledata['ec'].append(item_data[5])
                tabledata['a'].append(item_data[6])
            params['IFCOMPARE'] = 'yes'
            params['COMPARE_LIST'] = compare_list
        
        params['PAGE'] = 'bar.html'
        params['TABLEDATA'] = tabledata
        params['COMPAREBUTTON'] = 'yes'

        self.render_template('bar.html',params)

class PageQueueHandler(BaseHandler):
    def get(self):
        params = {}
        queryRes = json.loads(Native.dsn_cli_run('system.queue'))
        query_list = []
        for app in queryRes:
            for pool in app['thread_pool']:
                    for queue in pool['pool_queue']:
                        query_list.append({"queue_name":app['app_name']+'@'+pool['pool_name']+'@'+queue['name'],"queue_num":queue['num']})
        query_list = sorted(query_list, key=lambda queue: queue['queue_num'],reverse=True)[:8]
        params['QUEUE_LIST'] = map((lambda queue: queue['queue_name']),query_list)
        params['TABLEDATA'] = map((lambda queue: queue['queue_num']),query_list)
        self.render_template('queue.html',params)

class PageCliHandler(BaseHandler):
    def get(self):
        self.render_template('cli.html')

class PageBashHandler(BaseHandler):
    def get(self):
        self.render_template('bash.html')


class PageEditorHandler(BaseHandler):
    def get(self):
        params = {}
        dir = os.getcwd()
        working_dir = self.request.get('working_dir')
        file_name = self.request.get('file_name')
        if file_name != '':
            read_file = open(os.path.join(dir,working_dir, file_name),'r')
            content = read_file.read()
            read_file.close()
        else:
            content = ''

        dir_list = []
        lastPath = ''
        for d in working_dir.split('/'):
            if lastPath!='':
                lastPath += '/'
            lastPath +=d
            dir_list.append({'path':lastPath,'name':d})
        params['FILES'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isfile(os.path.join(dir,working_dir,f))]
        params['FILEFOLDERS'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isdir(os.path.join(dir,working_dir,f))]
        params['WORKING_DIR'] = working_dir
        params['DIR_LIST'] = dir_list
        params['CONTENT'] = content 
        params['FILE_NAME'] = file_name 
        
        self.render_template('editor.html',params)
    def post(self):
        content = self.request.get('content')
        dir = os.path.dirname(__file__)
        working_dir = self.request.get('working_dir')
        file_name = self.request.get('file_name')
        if file_name != '':
            write_file = open(os.path.join(dir,working_dir, file_name),'w')
            write_file.write(content)
            write_file.close()
            self.response.write("Successfully saved!")
        else:
            self.response.write("No file opened!")

class PageConfigureHandler(BaseHandler):
    def get(self):
        params = {}
        queryRes = Native.dsn_cli_run('config-dump')
        params['CONTENT'] = queryRes 
        self.render_template('configure.html',params)

class PageFileViewHandler(BaseHandler):
    def get(self):
        params = {}
        working_dir = self.request.get('working_dir')
        root_dir = self.request.get('root_dir')
        
        if root_dir == 'local':
            dir = os.path.dirname(GetMonitorDirPath()+'/local/')
        elif root_dir == 'app':
            dir = os.path.dirname(os.getcwd()+"/")
        elif root_dir == '':
            root_dir = 'app'
            dir = os.path.dirname(os.getcwd()+"/")
        

        try:
            params['FILES'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isfile(os.path.join(dir,working_dir,f))]
            params['FILEFOLDERS'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isdir(os.path.join(dir,working_dir,f))]
        except:
            self.response.write('Cannot find the specified file path, please check again')
            return

        dir_list = []
        lastPath = ''
        for d in working_dir.split('/'):
            if lastPath!='':
                lastPath += '/'
            lastPath +=d
            dir_list.append({'path':lastPath,'name':d})
        params['WORKING_DIR'] = working_dir
        params['ROOT_DIR'] = root_dir
        params['DIR_LIST'] = dir_list
        
        self.render_template('fileview.html',params)
    def post(self):
        params = {}
        dir = os.path.dirname(os.getcwd()+"/")
        working_dir = self.request.get('working_dir')
        
        try:
            raw_file = self.request.get('fileToUpload')
            file_name = self.request.get('file_name')
            savedFile = open(os.path.join(dir,working_dir,file_name),'wb')
            savedFile.write(raw_file)
            savedFile.close()

            params['RESPONSE'] = 'success'
        except:
            params['RESPONSE'] = 'fail'

        dir_list = []
        lastPath = ''
        for d in working_dir.split('/'):
            if lastPath!='':
                lastPath += '/'
            lastPath +=d
            dir_list.append({'path':lastPath,'name':d})
        params['FILES'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isfile(os.path.join(dir,working_dir,f))]
        params['FILEFOLDERS'] = [f for f in os.listdir(os.path.join(dir,working_dir)) if os.path.isdir(os.path.join(dir,working_dir,f))]
        params['WORKING_DIR'] = working_dir
        params['DIR_LIST'] = dir_list

        self.render_template('fileview.html',params)

class PageAnalyzerHandler(BaseHandler):
    def get(self):
        self.render_template('analyzer.html')


class PageViewHandler(BaseHandler):
    def get(self):
        self.render_template('counterview.html')
        
class PageStoreHandler(BaseHandler):
    def get(self):
        self.render_template('store.html')
    def post(self):
        raw_file = self.request.get('fileToUpload')
        raw_icon = self.request.get('iconToUpload')
        file_name = self.request.get('file_name')
        author = self.request.get('author')
        description = self.request.get('description')
        cluster_type = self.request.get('cluster_type')
        schema_info = self.request.get('schema_info')
        schema_type = self.request.get('schema_type')
        server_type = self.request.get('server_type')
        parameters = self.request.get('parameters')

        pack_dir = GetMonitorDirPath()+'/local/pack/'
        if not os.path.exists(pack_dir):
            os.makedirs(pack_dir)


        try:
            conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
            c = conn.cursor()
            check_table(c)

            c.execute("SELECT * FROM pack WHERE name = '" + file_name + "'")
            if c.fetchall()!=[]:
                conn.close()
                self.response.write('Upload fail! App "'+ file_name +'" already exists!')
                return
        
            uuid_val = str(uuid.uuid1())
            sql_cmd = "INSERT INTO pack VALUES " \
                    + "('" + file_name \
                    + "','" + author \
                    + "','" + description \
                    + "','" + uuid_val \
                    + "','" + cluster_type \
                    + "','" + schema_info \
                    + "','" + schema_type \
                    + "','" + server_type \
                    + "','" + parameters \
                    +  "');"

            c.execute(sql_cmd);
            conn.commit()

            conn.close()

            savedFile = open(pack_dir + uuid_val + '.7z', 'wb')
            savedFile.write(raw_file)
            savedFile.close()

            loc_of_7z = ''
            #to detect if 7z exists
            os_type = platform.system()
            if os_type == 'Windows':
                if subprocess.call(['where', '7z.exe']) == 0:
                    loc_of_7z = '7z.exe'
            elif os_type == 'Linux':
                if subprocess.call(['which', '7z']) == 0:
                    loc_of_7z = '7z'
            if loc_of_7z =='':
                self.response.write('Error: cannot find '+exe_of_7z)
                return

            subprocess.call([loc_of_7z,'x', pack_dir + uuid_val + '.7z','-y','-o'+pack_dir + '/' + uuid_val])

            
            iconFile = open(GetMonitorDirPath()+'/local/pack/'+ uuid_val + '.jpg', 'wb')
            iconFile.write(raw_icon)
            iconFile.close()

            return webapp2.redirect('/store.html')
        except:
            self.response.write('upload fail! Error:' + sys.exc_info()[0].__name__)

class PageServiceHandler(BaseHandler):
    def get(self):
        self.render_template('service.html')

class ApiCliHandler(BaseHandler):
    def get(self):
        command = self.request.get('command');
        queryRes = Native.dsn_cli_run(command)
        self.response.write(queryRes)
    def post(self):
        command = self.request.get('command');
        queryRes = Native.dsn_cli_run(command)

        self.response.headers['Access-Control-Allow-Origin'] = '*'

        self.response.write(queryRes)

class ApiBashHandler(BaseHandler):
    def get(self):
        command = self.request.get('command');
        queryRes = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE).stdout.read()
        self.response.write(queryRes)

class ApiValueHandler(BaseHandler):
    def get(self):
        task_code = self.request.get('task_code')
        if task_code=='':
            task_code = 'RPC_NFS_COPY'
        queryRes = Native.dsn_cli_run('pq counter_realtime '+task_code)
        self.response.write(queryRes)

class ApiPsutilHandler(BaseHandler):
    def get(self):
        queryRes = {}
        queryRes['cpu'] = psutil.cpu_percent(interval=1);
        queryRes['memory'] = psutil.virtual_memory()[2];
        queryRes['disk'] = psutil.disk_usage('/')[3];
        queryRes['networkio'] = psutil.net_io_counters()
        self.response.write(json.dumps(queryRes))

class ApiRemoteCounterSampleHandler(BaseHandler):
    def get(self):
        task_code = self.request.get('task_code')
        self.response.write(Native.dsn_cli_run('pq counter_sample '+task_code))

class ApiRemoteCounterCalcHandler(BaseHandler):
    def get(self):
        task_code = self.request.get('task_code')
        curr_percent = self.request.get('curr_percent')
        self.response.write(Native.dsn_cli_run('pq counter_calc '+task_code+' '+curr_percent if curr_percent!='50' else ''))

class ApiSaveViewHandler(BaseHandler):
    def post(self):
        name = self.request.get('name')
        author = self.request.get('author')
        description = self.request.get('description')
        counterList = self.request.get('counterList')
        graphtype = self.request.get('graphtype')
        interval = self.request.get('interval')

        local_dir = GetMonitorDirPath()+'/local/'
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)
        c.execute("DELETE FROM view WHERE name = '" + name + "';")

        c.execute("INSERT INTO view VALUES ('" + name + "','" + author + "','" + description + "','" + counterList + "','" + graphtype + "','" + interval + "');")
        conn.commit()

        conn.close()

        self.response.write('view "'+ name +'" is successfully saved!')

class ApiLoadViewHandler(BaseHandler):
    def post(self): 
        viewList = []

        local_dir = GetMonitorDirPath()+'/local/'
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)
        for view in c.execute('SELECT * FROM view'):
            viewList.append({'name':view[0],'author':view[1],'description':view[2],'counterList':view[3],'graphtype':view[4],'interval':view[5]})
        conn.close()
        self.SendJson(viewList)

class ApiDelViewHandler(BaseHandler):
    def post(self): 
        name = self.request.get('name')

        local_dir = GetMonitorDirPath()+'/local/'
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)
        c.execute("DELETE FROM view WHERE name = '" + name + "';")
        conn.commit()
        conn.close()

        self.response.write('success')

class ApiLoadPackHandler(BaseHandler):
    def post(self):
        packList = []

        pack_dir = GetMonitorDirPath()+'/local/pack/'
        if not os.path.exists(pack_dir):
            os.makedirs(pack_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)
        for pack in c.execute('SELECT * FROM pack'):
            packList.append({'name':pack[0],'author':pack[1],'description':pack[2],'uuid':pack[3],'cluster_type':pack[4]})
        conn.close()
        
        self.SendJson(packList)    


class ApiPackDetailHandler(BaseHandler):
    def post(self):
        pack_id = self.request.get('id')
        if pack_id == "" or not pack_id :
            self.response.write("missing parameter package id")
            return

        local_dir = GetMonitorDirPath()+'/local/'
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)

        c.execute("SELECT * FROM pack WHERE uuid = '" + pack_id + "'")
        pack_info = c.fetchone()
        conn.close()

        if pack_info == [] :
            self.response.write('cannot find the package : ' + pack_id)
            return

        ret = {'name' : pack_info[0], \
            'schema_info' : pack_info[5], \
            'schema_type' : pack_info[6], \
            'server_type' : pack_info[7], \
            'parameters' : pack_info[8]};
        self.SendJson(ret)


class ApiDelPackHandler(BaseHandler):
    def post(self):
        packName = self.request.get('name')
        pack_dir = GetMonitorDirPath()+'/local/pack/'
        if not os.path.exists(pack_dir):
            os.makedirs(pack_dir)

        conn = sqlite3.connect(GetMonitorDirPath()+'/local/'+'monitor.db')
        c = conn.cursor()
        check_table(c)

        c.execute("SELECT * FROM pack WHERE name = '" + packName + "'")
        packInfo = c.fetchone()
        if packInfo==[]:
            conn.close()
            self.response.write('Delete fail! App "'+ packName +'" doesn\'t exist!')
            return

        c.execute("DELETE FROM pack WHERE name = '" + packName + "';")
        conn.commit()
        conn.close()

        try:
            shutil.rmtree(os.path.join(pack_dir,packInfo[3]))
            os.remove(os.path.join(pack_dir,packInfo[3]+'.jpg'))
            os.remove(os.path.join(pack_dir,packInfo[3]+'.7z'))
        
            self.response.write('success')
        except:
            self.response.write('fail')
        
class ApiDeployPackHandler(BaseHandler):
    def post(self):
        name = self.request.get('name')
        package_id = self.request.get('id')
        cluster_name = self.request.get('cluster_name')

        package_full_path = GetMonitorDirPath() + '/local/pack/' + package_id + '.7z'

        #in order to use dsn_primary_address, use one empty command to trigger mimic 
        mimic_trigger = Native.dsn_cli_run('')
        package_server = Native.dsn_primary_address()
        
        req = {"deploy_request":{"cluster_name":cluster_name, "name":name, "package_full_path":package_full_path, "package_id":package_id, "package_server":package_server}}
        self.response.write(Native.dsn_cli_run('server.deploy ' + json.dumps(req).replace(" ", "")))

def start_http_server(portNum):  
    static_app = webob.static.DirectoryApp(GetMonitorDirPath() + "/static")
    web_app = webapp2.WSGIApplication([
    ('/', PageMainHandler),
    ('/main.html', PageMainHandler),
    ('/table.html', PageTableHandler),
    ('/sample.html', PageSampleHandler),
    ('/value.html', PageValueHandler),
    ('/bar.html', PageBarHandler),
    ('/queue.html', PageQueueHandler),
    ('/cli.html', PageCliHandler),
    ('/bash.html', PageBashHandler),
    ('/editor.html', PageEditorHandler),
    ('/configure.html', PageConfigureHandler),
    ('/fileview.html', PageFileViewHandler),
    ('/analyzer.html', PageAnalyzerHandler),
    ('/view.html', PageViewHandler),
    ('/store.html', PageStoreHandler),
    ('/service.html', PageServiceHandler),

    ('/api/cli', ApiCliHandler),
    ('/api/bash', ApiBashHandler),
    ('/api/value', ApiValueHandler),
    ('/api/psutil', ApiPsutilHandler),
    ('/api/remoteCounterSample', ApiRemoteCounterSampleHandler),
    ('/api/remoteCounterCalc', ApiRemoteCounterCalcHandler),
    ('/api/view/save', ApiSaveViewHandler),
    ('/api/view/load', ApiLoadViewHandler),
    ('/api/view/del', ApiDelViewHandler),
    ('/api/pack/load', ApiLoadPackHandler),
    ('/api/pack/detail', ApiPackDetailHandler),
    ('/api/pack/del', ApiDelPackHandler),
    ('/api/pack/deploy', ApiDeployPackHandler),

    ('/app/(.+)', AppStaticFileHandler),
    ('/local/(.+)', LocalStaticFileHandler),
], debug=True)

    app_list = Cascade([static_app, web_app])

    httpserver.serve(app_list, host='0.0.0.0', port=str(portNum))
