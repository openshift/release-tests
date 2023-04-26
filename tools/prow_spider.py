#coding:utf-8
import requests
from fake_useragent import UserAgent
import time
import random
from lxml import etree


class ProwSpider(object):
    def __init__(self):
        # config the based URL here
        self.url='https://github.com/openshift/release/blob/master/ci-operator/config/openshift/openshift-tests-private/'
        self.blog=1
        
    def get_header(self):
        ua=UserAgent()
        headers={'User-Agent':ua.random}
        return headers
    
    def get_html(self,url):
        if self.blog <= 3:
            try:
                res=requests.get(url=url,headers=self.get_header(),timeout=3)
                html=res.text
                return html
            except Exception as e:
                print(e)
                self.blog+=1
                self.get_html(url)

    def parse_html(self,url):
        html=self.get_html(url)
        if html:
            p=etree.HTML(html)
            span_list=p.xpath('//td[@class="blob-code blob-code-inner js-file-line"]')
            # print(span_list)
            for span in span_list:
                # query the content if is 'as', and then get the job name
                content=span.xpath('.//span[@class="pl-ent"]/text()')
                if len(content) > 0 and content[0] == "as":
                    name=span.xpath('.//span[@class="pl-s"]/text()')
                    if len(name) > 0:
                        print(name[0].strip())


    def run(self):
        try:
            file_name=input('Please input the file name you want to query:')
            url = self.url + file_name
            print(url)
            self.parse_html(url)
            time.sleep(random.randint(1,3))
            self.blog=1
        except Exception as e:
            print('Fatal error:', e)

if __name__ == '__main__':
    start=time.time()
    spider=ProwSpider()
    spider.run()
    end=time.time()
    print('execute time cost:%.2f'%(end-start))